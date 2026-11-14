"""登录态：第一版只识别「已登录」（主窗口 + 可读会话列表）。

扫码 / 一键登录 / 退出由用户在微信客户端完成；对应 RPC 返回未实现。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

PHASE_UNSPECIFIED = "unspecified"
PHASE_STARTING = "starting"
PHASE_QR_READY = "qr_ready"
PHASE_ONE_CLICK_READY = "one_click_ready"
PHASE_WAIT_PHONE = "wait_phone"
PHASE_LOGGED_IN = "logged_in"
PHASE_UNKNOWN = "unknown"


class LoginMachine:
    """Poll whether WeChat looks logged-in; notify WatchLogin subscribers."""

    def __init__(self, poll_interval: float = 2.0) -> None:
        """Create a poller; start() begins the background thread."""
        self.poll_interval = poll_interval
        self._phase = PHASE_STARTING
        self._detail = "starting"
        self._since_ms = int(time.time() * 1000)
        self._started_at = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._subs: list[deque] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background poll loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="malus-login", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background poll loop."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def uptime_ms(self) -> int:
        """Milliseconds since this machine was constructed."""
        return int((time.time() - self._started_at) * 1000)

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of the current login snapshot."""
        with self._lock:
            return {
                "phase": self._phase,
                "detail": self._detail,
                "since_unix_ms": self._since_ms,
                "markers": [],
            }

    def subscribe(self) -> deque:
        """Register for phase-change snapshots."""
        q: deque = deque(maxlen=32)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: deque) -> None:
        """Drop a subscriber queue."""
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _set(self, phase: str, detail: str) -> None:
        """Update phase and notify subscribers when it changes."""
        with self._lock:
            if phase == self._phase and detail == self._detail:
                return
            self._phase = phase
            self._detail = detail
            self._since_ms = int(time.time() * 1000)
            snap = {
                "phase": phase,
                "detail": detail,
                "since_unix_ms": self._since_ms,
                "markers": [],
            }
            for q in self._subs:
                q.append(snap)

    def _loop(self) -> None:
        """Background: detect WeChat + chat list readability."""
        from . import ax, chat

        while not self._stop.is_set():
            try:
                if not ax.check_trusted():
                    self._set(PHASE_UNKNOWN, "accessibility_not_trusted")
                elif ax.find_wechat_pid() is None:
                    self._set(PHASE_UNKNOWN, "wechat_not_running")
                elif not ax.windows():
                    self._set(PHASE_UNKNOWN, "no_wechat_window")
                elif not ax.ax_content_usable():
                    self._set(PHASE_UNKNOWN, "ax_content_missing")
                else:
                    chats = chat.list_chats()
                    if chats:
                        self._set(PHASE_LOGGED_IN, f"chats={len(chats)}")
                    else:
                        self._set(PHASE_UNKNOWN, "chat_list_empty")
            except Exception as exc:
                self._set(PHASE_UNKNOWN, f"poll_error:{type(exc).__name__}")
            self._stop.wait(self.poll_interval)
