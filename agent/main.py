"""MalusCallus gRPC 服务：本机驱动 Mac 微信，线协议与 Callus / WeJam 兼容。"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from concurrent import futures

import grpc

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))

from wejam.v1 import wejam_pb2, wejam_pb2_grpc  # noqa: E402

from . import ax, chat, login, selflog  # noqa: E402
from . import input_mac as inputmod  # noqa: E402
from .redact import install_agent_log_filter  # noqa: E402

PORT = int(os.environ.get("WEJAM_PORT", os.environ.get("MALUS_PORT", "7701")))
PHASE_TO_PROTO = {
    login.PHASE_UNSPECIFIED: wejam_pb2.LOGIN_PHASE_UNSPECIFIED,
    login.PHASE_STARTING: wejam_pb2.LOGIN_PHASE_STARTING,
    login.PHASE_QR_READY: wejam_pb2.LOGIN_PHASE_QR_READY,
    login.PHASE_ONE_CLICK_READY: wejam_pb2.LOGIN_PHASE_ONE_CLICK_READY,
    login.PHASE_WAIT_PHONE: wejam_pb2.LOGIN_PHASE_WAIT_PHONE,
    login.PHASE_LOGGED_IN: wejam_pb2.LOGIN_PHASE_LOGGED_IN,
    login.PHASE_UNKNOWN: wejam_pb2.LOGIN_PHASE_UNKNOWN,
}


def _unimplemented(context, feature: str) -> None:
    """Abort with UNIMPLEMENTED and a clear MalusCallus message."""
    context.abort(
        grpc.StatusCode.UNIMPLEMENTED,
        f"MalusCallus v0.1 未实现: {feature}",
    )


class WeJamServicer(wejam_pb2_grpc.WeJamServicer):
    """wejam.v1 surface backed by macOS AX + CGEvent."""

    def __init__(self, machine: login.LoginMachine) -> None:
        """Hold the login poller used by Get/WatchLogin."""
        self.machine = machine

    def GetStatus(self, request, context):
        """Return whether WeChat looks ready and current login phase."""
        snap = self.machine.snapshot()
        return wejam_pb2.Status(
            ready=snap["phase"] == login.PHASE_LOGGED_IN,
            wechat_version="macOS",
            login_phase=PHASE_TO_PROTO.get(
                snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED
            ),
            uptime_ms=self.machine.uptime_ms(),
        )

    def _state_msg(self, snap=None):
        """Build a LoginState protobuf from a snapshot dict."""
        snap = snap or self.machine.snapshot()
        return wejam_pb2.LoginState(
            phase=PHASE_TO_PROTO.get(snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED),
            detail=snap["detail"],
            since_unix_ms=snap["since_unix_ms"],
            markers=snap.get("markers") or [],
        )

    def GetLoginState(self, request, context):
        """Return the current login phase."""
        return self._state_msg()

    def WatchLogin(self, request, context):
        """Stream login phase changes until the client disconnects."""
        q = self.machine.subscribe()
        try:
            yield self._state_msg()
            while context.is_active():
                try:
                    snap = q.popleft()
                except IndexError:
                    time.sleep(0.3)
                    continue
                yield self._state_msg(snap)
        finally:
            self.machine.unsubscribe(q)

    def GetLoginQRCode(self, request, context):
        """First version: QR login automation not implemented."""
        _unimplemented(context, "GetLoginQRCode")

    def SubmitLogin(self, request, context):
        """First version: one-click login not implemented."""
        _unimplemented(context, "SubmitLogin")

    def Logout(self, request, context):
        """First version: GUI logout automation not implemented."""
        _unimplemented(context, "Logout")

    def GetAccountSummary(self, request, context):
        """Minimal account summary from login snapshot."""
        snap = self.machine.snapshot()
        return wejam_pb2.AccountSummary(
            logged_in=snap["phase"] == login.PHASE_LOGGED_IN,
            wechat_version="macOS",
            login_phase=PHASE_TO_PROTO.get(
                snap["phase"], wejam_pb2.LOGIN_PHASE_UNSPECIFIED
            ),
            login_detail=snap["detail"],
            login_since_unix_ms=snap["since_unix_ms"],
            uptime_ms=self.machine.uptime_ms(),
        )

    def ListChats(self, request, context):
        """Return session-list rows."""
        rows = chat.list_chats()
        return wejam_pb2.ListChatsResponse(
            chats=[
                wejam_pb2.Chat(
                    name=c["name"],
                    last_message=c.get("last_message", ""),
                    last_time=c.get("last_time", ""),
                    unread_count=int(c.get("unread_count") or 0),
                    pinned=bool(c.get("pinned")),
                    muted=bool(c.get("muted")),
                )
                for c in rows
            ]
        )

    def ListMessages(self, request, context):
        """Return the visible message window for a chat."""
        try:
            name, msgs = chat.list_messages(request.chat, request.limit)
        except chat.AxContentMissing as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except RuntimeError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        info = chat.chat_header_info(name)
        return wejam_pb2.ListMessagesResponse(
            chat=name,
            chat_type=info.get("chat_type", ""),
            member_count=int(info.get("member_count") or 0),
            messages=[
                wejam_pb2.Message(
                    id=m["id"],
                    chat=m["chat"],
                    sender=m["sender"],
                    text=m["text"],
                    time_text=m["time_text"],
                    kind=getattr(wejam_pb2, f"MESSAGE_KIND_{m['kind']}"),
                    index=m["index"],
                    from_self=selflog.is_own(m["chat"], m["text"]),
                    content_type=m.get("content_type", "text"),
                    stable_id=m.get("stable_id", ""),
                )
                for m in msgs
            ],
        )

    def WatchMessages(self, request, context):
        """Diff-push new messages (global preview or single chat)."""
        if not request.chat:
            yield from self._watch_global(context)
        else:
            yield from self._watch_single(request.chat, context)

    @staticmethod
    def _is_new_message(prev, cur) -> bool:
        """True when session preview indicates a new inbound message."""
        if cur["last_message"] != prev["last_message"]:
            return True
        if cur["last_time"] != prev["last_time"]:
            return True
        return cur["unread_count"] > prev["unread_count"]

    @staticmethod
    def _preview_to_message(c):
        """Turn one session-list preview row into a preview_only Message."""
        from .sender_name import split_preview_sender

        sender, text = split_preview_sender(c["last_message"])
        mid = hashlib.sha1(
            f"{c['name']}|{c['last_message']}|{c['last_time']}|{c['unread_count']}".encode()
        ).hexdigest()[:16]
        return wejam_pb2.Message(
            id=mid,
            chat=c["name"],
            sender=sender,
            text=text,
            time_text=c["last_time"],
            kind=wejam_pb2.MESSAGE_KIND_TEXT,
            preview_only=True,
            from_self=selflog.is_own(c["name"], c["last_message"]),
        )

    def _watch_global(self, context):
        """Poll session-list previews without opening chats."""
        prev: dict = {}
        while context.is_active():
            try:
                chats = chat.list_chats()
            except Exception:
                time.sleep(1.5)
                continue
            cur = {c["name"]: c for c in chats}
            if prev:
                changed = [
                    c
                    for name, c in cur.items()
                    if name in prev and self._is_new_message(prev[name], c)
                ]
                for c in changed:
                    yield wejam_pb2.MessageEvent(
                        chat=c["name"],
                        at_unix_ms=int(time.time() * 1000),
                        added=[self._preview_to_message(c)],
                        unread=c["unread_count"],
                    )
            prev = cur
            time.sleep(1.0)

    def _watch_single(self, target, context):
        """Keep one chat open and push newly appeared TEXT bubbles."""
        seen: set = set()
        last_chat = None
        settle_until = 0.0
        while context.is_active():
            try:
                name, msgs = chat.list_messages(target, 0)
            except Exception:
                time.sleep(1.0)
                continue
            texts = [(m["chat"], m["id"]) for m in msgs if m["kind"] == "TEXT"]
            if name != last_chat:
                last_chat = name
                seen = set(texts)
                settle_until = time.time() + 3.0
                time.sleep(1.5)
                continue
            if time.time() < settle_until:
                seen |= set(texts)
                time.sleep(1.5)
                continue
            added = [
                m
                for m in msgs
                if m["kind"] == "TEXT" and (m["chat"], m["id"]) not in seen
            ]
            if added:
                seen.update((m["chat"], m["id"]) for m in added)
                yield wejam_pb2.MessageEvent(
                    chat=target,
                    at_unix_ms=int(time.time() * 1000),
                    added=[
                        wejam_pb2.Message(
                            id=m["id"],
                            chat=m["chat"],
                            sender=m["sender"],
                            text=m["text"],
                            time_text=m["time_text"],
                            kind=getattr(wejam_pb2, f"MESSAGE_KIND_{m['kind']}"),
                            index=m["index"],
                            from_self=selflog.is_own(m["chat"], m["text"]),
                        )
                        for m in added
                    ],
                )
            time.sleep(1.5)

    def SendText(self, request, context):
        """Send one text bubble via CGEvent Unicode injection."""
        ok, detail = chat.send_text(request.chat, request.text)
        return wejam_pb2.SendResult(ok=ok, detail=detail)

    def InvokeMessage(self, request, context):
        """Context-menu actions not in v0.1."""
        _unimplemented(context, "InvokeMessage")

    def ReadContext(self, request, context):
        """Scroll-collect context deferred until AX scroll is proven."""
        _unimplemented(context, "ReadContext")

    def ReadLatest(self, request, context):
        """Newest visible bubble including sender."""
        try:
            latest = chat.read_latest(request.chat)
        except chat.AxContentMissing as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        except RuntimeError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        if latest is None:
            return wejam_pb2.ReadLatestResponse()
        msg = wejam_pb2.Message(
            id=latest["id"],
            chat=latest["chat"],
            sender=latest.get("sender", ""),
            text=latest["text"],
            time_text=latest.get("time_text", ""),
            kind=getattr(wejam_pb2, f"MESSAGE_KIND_{latest.get('kind', 'TEXT')}"),
            index=int(latest.get("index") or 0),
            from_self=selflog.is_own(latest["chat"], latest["text"]),
            content_type=latest.get("content_type", "text"),
            stable_id=latest.get("stable_id", ""),
        )
        return wejam_pb2.ReadLatestResponse(message=msg)

    def CaptureMessageMedia(self, request, context):
        """Bubble crop deferred until AX frames are stable."""
        _unimplemented(context, "CaptureMessageMedia")

    def GetBadges(self, request, context):
        """Pixel badge scan not in v0.1."""
        _unimplemented(context, "GetBadges")

    def DumpA11yTree(self, request, context):
        """Dump the WeChat AX tree for selector probing."""
        only_visible = request.only_visible if request.HasField("only_visible") else True
        depth = request.max_depth if request.HasField("max_depth") else 20
        nodes = chat.dump_tree_rows(
            only_visible=only_visible,
            max_depth=depth or 20,
        )
        return wejam_pb2.DumpA11yTreeResponse(
            nodes=[
                wejam_pb2.A11yNode(
                    depth=n["depth"],
                    role=n["role"],
                    name=n["name"],
                    text=n["text"],
                    states=n["states"],
                )
                for n in nodes
            ]
        )

    def InvokeNode(self, request, context):
        """Click a node matched by role + name (escape hatch)."""
        needle_role = request.role or ""
        needle_name = request.name or ""

        def pred(n):
            role_ok = (not needle_role) or needle_role in (n.role or "")
            name_ok = (not needle_name) or needle_name in (n.title or n.label or "")
            return role_ok and name_ok and n.w > 0 and n.h > 0

        node = ax.find_first(pred, max_depth=28)
        if node is None:
            return wejam_pb2.InvokeNodeResponse(ok=False, detail="未找到匹配的可见节点")
        x, y = node.center
        inputmod.click_at(x, y)
        return wejam_pb2.InvokeNodeResponse(
            ok=True,
            detail=f"已点击 {node.role}/{node.label} @ ({int(x)},{int(y)})",
        )


def serve() -> None:
    """Start the gRPC server after verifying Accessibility trust."""
    install_agent_log_filter()
    if not ax.check_trusted():
        print(
            "[maluscallus] 未获得辅助功能权限。\n"
            "请打开：系统设置 → 隐私与安全性 → 辅助功能，\n"
            "勾选运行本进程的终端 / Cursor / Python，然后重试。",
            flush=True,
        )
        sys.exit(2)
    if ax.find_wechat_pid() is None:
        print("[maluscallus] 未找到正在运行的微信 (WeChat.app)。请先打开微信。", flush=True)
        sys.exit(3)

    machine = login.LoginMachine(
        poll_interval=float(os.environ.get("WEJAM_POLL", "2.0")),
    )
    machine.start()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    wejam_pb2_grpc.add_WeJamServicer_to_server(WeJamServicer(machine), server)
    server.add_insecure_port(f"127.0.0.1:{PORT}")
    server.start()
    print(f"[maluscallus] gRPC listening on 127.0.0.1:{PORT}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        machine.stop()
        server.stop(0)


if __name__ == "__main__":
    serve()
