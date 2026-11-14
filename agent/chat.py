"""会话与消息：用 macOS AX 树读会话列表 / 消息，并用 CGEvent 发送文本。

选择器在本机 DumpA11yTree 探测后填写；启发式回退覆盖常见「会话」「消息」标题。
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from . import ax, input_mac, parse, selflog
from .sender_name import split_preview_sender
from .ui import synchronized

# Env overrides after probe (comma-separated role substrings or exact titles).
CHAT_LIST_TITLE = os.environ.get("MALUS_CHAT_LIST_TITLE", "会话")
MESSAGE_LIST_TITLE = os.environ.get("MALUS_MESSAGE_LIST_TITLE", "消息")
SEARCH_TITLES = ("搜索", "Search")

_last_count: dict[str, int] = {}


def _role_is(node: ax.AxNode, *roles: str) -> bool:
    """True when node.role equals or ends with one of the given role names."""
    r = node.role or ""
    short = r.split(".")[-1] if r else ""
    for want in roles:
        if r == want or short == want or r.endswith(want):
            return True
    return False


def _title_matches(node: ax.AxNode, needle: str) -> bool:
    """True when title/label contains the needle."""
    if not needle:
        return False
    blob = f"{node.title}|{node.label}|{node.description}"
    return needle in blob


def _find_list_by_title(title: str) -> ax.AxNode | None:
    """Find an AXList / AXTable / AXScrollArea whose title matches."""

    def pred(n: ax.AxNode) -> bool:
        if not _title_matches(n, title):
            return False
        return _role_is(
            n,
            "AXList",
            "AXTable",
            "AXOutline",
            "AXScrollArea",
            "AXGroup",
            "list",
        )

    return ax.find_first(pred, max_depth=28)


def _list_item_children(container: ax.AxNode) -> list[ax.AxNode]:
    """Direct children that look like rows / cells under a list container."""
    kids = [ax.snapshot(c, container.depth + 1) for c in ax.children_of(container.element)]
    rows: list[ax.AxNode] = []
    for k in kids:
        if _role_is(
            k,
            "AXRow",
            "AXCell",
            "AXGroup",
            "AXStaticText",
            "AXButton",
            "AXListItem",
            "list item",
        ):
            rows.append(k)
        elif k.w > 40 and k.h > 20 and k.label:
            rows.append(k)
    # If container itself is a scroll area, dig one level into the first list child.
    if not rows:
        for k in kids:
            if _role_is(k, "AXList", "AXTable", "AXOutline", "list"):
                return _list_item_children(k)
    return rows


def _item_text(node: ax.AxNode) -> str:
    """Concatenate label + descendant static texts for a list row."""
    parts: list[str] = []
    if node.label:
        parts.append(node.label)
    for child in ax.walk(node.element, max_depth=4):
        if child.element is node.element:
            continue
        if child.label and child.label not in parts:
            # Prefer multi-line assembly for session rows.
            if _role_is(child, "AXStaticText", "AXTextField", "AXTextArea"):
                parts.append(child.label)
    # Deduplicate while preserving order; join with newlines like Linux Callus.
    seen: set[str] = set()
    lines: list[str] = []
    for p in parts:
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        lines.append(p)
    if len(lines) == 1:
        return lines[0]
    return "\n".join(lines)


class AxContentMissing(RuntimeError):
    """Raised when Mac WeChat exposes no usable AX content for chats/messages."""


def ensure_ax_content() -> None:
    """Fail fast when the WeChat window has chrome-only accessibility."""
    if ax.find_wechat_pid() is None:
        raise AxContentMissing("未找到正在运行的微信 (WeChat.app)")
    if not ax.windows():
        raise AxContentMissing("微信无可见窗口；请打开主窗口后再试")
    if not ax.ax_content_usable():
        raise AxContentMissing(
            "Mac 微信窗口未向辅助功能暴露会话/消息/输入框（仅有标题栏按钮）。"
            "详见 docs/probe.md；请勿改用 OCR。"
        )


@synchronized
def list_chats() -> list[dict]:
    """读会话列表；找不到容器时返回空列表。"""
    if not ax.ax_content_usable():
        return []
    container = _find_list_by_title(CHAT_LIST_TITLE)
    if container is None:
        # Heuristic: widest left-side scroll/list with many text children.
        container = _heuristic_chat_list()
    if container is None:
        return []
    out: list[dict] = []
    for row in _list_item_children(container):
        raw = _item_text(row)
        parsed = parse.parse_chat_item(raw)
        if parsed and parsed["name"]:
            # Attach AX element for open_chat clicks.
            parsed["_node"] = row
            out.append(parsed)
    return out


def _heuristic_chat_list() -> ax.AxNode | None:
    """Guess the session list: tall narrow scroll/list on the left of the main window."""
    wins = ax.windows()
    if not wins:
        return None
    main = ax.snapshot(wins[0], 0)
    candidates = ax.find_all(
        lambda n: _role_is(n, "AXList", "AXScrollArea", "AXOutline", "AXTable")
        and n.w > 120
        and n.h > 200
        and n.x < main.x + main.w * 0.45,
        max_depth=20,
        root=wins[0],
    )
    best: ax.AxNode | None = None
    best_score = -1
    for c in candidates:
        rows = _list_item_children(c)
        score = len(rows) * 10 + int(c.h)
        if score > best_score:
            best_score = score
            best = c
    return best


@synchronized
def current_chat() -> str:
    """Infer the open chat name from the input box / window title."""
    box = input_box_node()
    if box is not None and box.title and box.title not in SEARCH_TITLES:
        return box.title.strip()
    # Window title sometimes is the chat name.
    for w in ax.windows():
        title = ax.attr_str(w, "AXTitle")
        if title and title not in ("WeChat", "微信", ""):
            return title.strip()
    return ""


@synchronized
def input_box_node() -> ax.AxNode | None:
    """Locate the message composer (editable text, not the search field)."""

    def pred(n: ax.AxNode) -> bool:
        if not _role_is(n, "AXTextArea", "AXTextField", "AXComboBox", "text"):
            return False
        label = n.label
        if any(s in label for s in SEARCH_TITLES):
            return False
        # Prefer bottom-area large fields.
        return n.w > 80 and n.h >= 20

    nodes = ax.find_all(pred, max_depth=28)
    if not nodes:
        return None
    # Bottom-most in the main window.
    nodes.sort(key=lambda n: (n.y + n.h, n.w), reverse=True)
    return nodes[0]


@synchronized
def input_text() -> str:
    """Current contents of the composer."""
    node = input_box_node()
    if node is None:
        return ""
    return (node.value or node.title or "").strip()


@synchronized
def open_chat(name: str) -> tuple[bool, str]:
    """Click the session row matching name. Returns (ok, detail)."""
    if not name:
        return False, "empty chat name"
    ax.bring_wechat_front()
    time.sleep(0.2)
    if name == current_chat():
        return True, "已经是当前会话"
    chats = list_chats()
    for c in chats:
        if c["name"] == name:
            node = c.get("_node")
            if node is None:
                continue
            x, y = node.center
            input_mac.click_at(x, y)
            time.sleep(0.5)
            return True, f"已打开 {name}"
    return False, f"未找到会话 {name!r}"


@synchronized
def list_messages(chat: str = "", limit: int = 0) -> tuple[str, list[dict]]:
    """读当前（或指定）会话可见消息窗口。"""
    ensure_ax_content()
    if chat:
        ok, detail = open_chat(chat)
        if not ok:
            raise RuntimeError(detail)
    name = chat or current_chat()
    container = _find_list_by_title(MESSAGE_LIST_TITLE)
    if container is None:
        container = _heuristic_message_list()
    if container is None:
        return name, []

    rows = _list_item_children(container)
    msgs: list[dict] = []
    time_text = ""
    index = 0
    for row in rows:
        raw = _item_text(row).strip()
        if not raw:
            continue
        if parse.is_time_row(raw):
            time_text = raw
            continue
        sender, body = split_preview_sender(raw)
        text = body or raw
        content_type = parse.classify_content(text)
        kind = "SYSTEM" if content_type == "system" else "TEXT"
        mid = hashlib.sha1(f"{name}|{index}|{text}|{time_text}".encode()).hexdigest()[:16]
        msgs.append(
            {
                "id": mid,
                "chat": name,
                "sender": sender,
                "text": text,
                "time_text": time_text,
                "kind": kind,
                "index": index,
                "content_type": content_type,
                "stable_id": mid,
            }
        )
        index += 1

    if limit and limit > 0:
        msgs = msgs[-limit:]
    _last_count[name] = len(msgs)
    return name, msgs


def _heuristic_message_list() -> ax.AxNode | None:
    """Guess the message pane: large scroll/list in the right/center of the window."""
    wins = ax.windows()
    if not wins:
        return None
    main = ax.snapshot(wins[0], 0)
    candidates = ax.find_all(
        lambda n: _role_is(n, "AXList", "AXScrollArea", "AXOutline", "AXTable", "AXGroup")
        and n.w > 200
        and n.h > 200
        and n.x > main.x + main.w * 0.25,
        max_depth=22,
        root=wins[0],
    )
    best: ax.AxNode | None = None
    best_score = -1
    for c in candidates:
        rows = _list_item_children(c)
        score = len(rows) * 5 + int(c.w + c.h)
        if score > best_score:
            best_score = score
            best = c
    return best


@synchronized
def chat_header_info(chat: str) -> dict[str, Any]:
    """Best-effort chat_type / member_count (Mac GUI often lacks member count)."""
    return {"chat_type": "", "member_count": 0}


@synchronized
def send_text(chat: str, text: str) -> tuple[bool, str]:
    """打开会话、注入 Unicode、回车，并检查输入框是否清空。"""
    if not (text or "").strip():
        return False, "empty text"
    try:
        ensure_ax_content()
    except AxContentMissing as exc:
        return False, str(exc)
    ax.bring_wechat_front()
    time.sleep(0.15)
    if chat:
        ok, detail = open_chat(chat)
        if not ok:
            return False, detail
    target = chat or current_chat()
    box = input_box_node()
    if box is None:
        return False, "找不到输入框"
    x, y = box.center
    input_mac.click_at(x, y)
    time.sleep(0.25)
    input_mac.type_text(text)
    time.sleep(0.25)
    for _ in (1, 2):
        input_mac.tap_return()
        for _wait in range(6):
            time.sleep(0.3)
            if not input_text():
                selflog.remember(target, text)
                return True, f"已发送 {len(text)} 个字符到 {target}"
    return False, f"消息似乎没有发出（输入框仍有内容），目标 {target}"


@synchronized
def read_latest(chat: str = "") -> dict | None:
    """最新一条可见文本消息（含 sender），不等滚动。"""
    name, msgs = list_messages(chat, 0)
    texts = [m for m in msgs if m.get("kind") == "TEXT"]
    if not texts:
        return None
    latest = texts[-1]
    latest["chat"] = name or latest.get("chat", "")
    return latest


def dump_tree_rows(
    *,
    only_visible: bool = True,
    max_depth: int = 20,
) -> list[dict]:
    """Serialize AX nodes for DumpA11yTree RPC / probe scripts."""
    rows: list[dict] = []
    for node in ax.walk(max_depth=max_depth):
        if only_visible and (node.w <= 0 or node.h <= 0):
            # Keep nodes without frame if they have a label (some menus).
            if not node.label:
                continue
        states: list[str] = []
        if node.w > 0 and node.h > 0:
            states.append("framed")
        rows.append(
            {
                "depth": node.depth,
                "role": node.role,
                "name": node.title or node.description,
                "text": node.value or (node.label if node.label != node.title else ""),
                "states": states,
            }
        )
    return rows
