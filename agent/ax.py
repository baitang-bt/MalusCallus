"""macOS Accessibility (AXUIElement) 读取：找微信进程、遍历树、取 frame。

未授权辅助功能时 check_trusted() 为 False；服务启动应直接退出并提示用户。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator

from ApplicationServices import (  # type: ignore
    AXIsProcessTrusted,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementPerformAction,
    AXValueGetValue,
    kAXChildrenAttribute,
    kAXDescriptionAttribute,
    kAXErrorSuccess,
    kAXPositionAttribute,
    kAXPressAction,
    kAXRoleAttribute,
    kAXSizeAttribute,
    kAXTitleAttribute,
    kAXValueAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXWindowsAttribute,
)
from Cocoa import NSRunningApplication, NSWorkspace  # type: ignore

# Preferred bundle ids for WeChat on macOS (main app first).
WECHAT_BUNDLES = (
    "com.tencent.xinWeChat",
    "com.tencent.flue.WeChatAppEx",
)


@dataclass(frozen=True)
class AxNode:
    """One accessibility node snapshot used by chat selectors and DumpA11yTree."""

    element: Any
    role: str
    title: str
    value: str
    description: str
    depth: int
    x: float
    y: float
    w: float
    h: float

    @property
    def label(self) -> str:
        """Best human-readable string among title / value / description."""
        for s in (self.title, self.value, self.description):
            if s and s.strip():
                return s.strip()
        return ""

    @property
    def center(self) -> tuple[float, float]:
        """Click target at the geometric center of the node frame."""
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)


def check_trusted() -> bool:
    """Return True when this process may use Accessibility APIs."""
    return bool(AXIsProcessTrusted())


def find_wechat_pid() -> int | None:
    """Return the PID of a running WeChat-related app, or None."""
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    by_bundle: dict[str, int] = {}
    for app in apps:
        bid = str(app.bundleIdentifier() or "")
        if bid in WECHAT_BUNDLES:
            by_bundle[bid] = int(app.processIdentifier())
        name = str(app.localizedName() or "")
        if name in ("WeChat", "微信") and bid:
            by_bundle.setdefault(bid, int(app.processIdentifier()))
    for bid in WECHAT_BUNDLES:
        if bid in by_bundle:
            return by_bundle[bid]
    # Fallback: any process whose name is WeChat.
    for app in apps:
        if str(app.localizedName() or "") in ("WeChat", "微信"):
            return int(app.processIdentifier())
    return None


def app_element(pid: int | None = None) -> Any | None:
    """Build the root AXUIElement for WeChat (or the given pid)."""
    use_pid = pid if pid is not None else find_wechat_pid()
    if use_pid is None:
        return None
    return AXUIElementCreateApplication(use_pid)


def _copy_attr(element: Any, attr: str) -> Any | None:
    """Copy one AX attribute; return None on failure."""
    err, value = AXUIElementCopyAttributeValue(element, attr, None)
    if err != kAXErrorSuccess:
        return None
    return value


def attr_str(element: Any, attr: str) -> str:
    """Read a string attribute, empty when missing."""
    value = _copy_attr(element, attr)
    if value is None:
        return ""
    return str(value)


def children_of(element: Any) -> list[Any]:
    """Return direct AX children (empty list on error)."""
    value = _copy_attr(element, kAXChildrenAttribute)
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def frame_of(element: Any) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) in global screen points; zeros when unavailable."""
    pos = _copy_attr(element, kAXPositionAttribute)
    size = _copy_attr(element, kAXSizeAttribute)
    x = y = w = h = 0.0
    if pos is not None:
        ok, point = AXValueGetValue(pos, kAXValueCGPointType, None)
        if ok and point is not None:
            x = float(point.x)
            y = float(point.y)
    if size is not None:
        ok, sz = AXValueGetValue(size, kAXValueCGSizeType, None)
        if ok and sz is not None:
            w = float(sz.width)
            h = float(sz.height)
    return x, y, w, h


def snapshot(element: Any, depth: int = 0) -> AxNode:
    """Build an AxNode from a live AXUIElement."""
    x, y, w, h = frame_of(element)
    return AxNode(
        element=element,
        role=attr_str(element, kAXRoleAttribute),
        title=attr_str(element, kAXTitleAttribute),
        value=attr_str(element, kAXValueAttribute),
        description=attr_str(element, kAXDescriptionAttribute),
        depth=depth,
        x=x,
        y=y,
        w=w,
        h=h,
    )


def windows(pid: int | None = None) -> list[Any]:
    """Return AX windows for WeChat."""
    root = app_element(pid)
    if root is None:
        return []
    wins = _copy_attr(root, kAXWindowsAttribute)
    if wins is None:
        return []
    try:
        return list(wins)
    except TypeError:
        return []


def walk(
    element: Any | None = None,
    *,
    max_depth: int = 30,
    only_with_frame: bool = False,
) -> Iterator[AxNode]:
    """Depth-first walk of the WeChat AX tree (or a subtree)."""
    root = element if element is not None else app_element()
    if root is None:
        return

    def rec(el: Any, depth: int) -> Iterator[AxNode]:
        if depth > max_depth:
            return
        node = snapshot(el, depth)
        if only_with_frame and (node.w <= 0 or node.h <= 0):
            pass
        else:
            yield node
        for child in children_of(el):
            yield from rec(child, depth + 1)

    yield from rec(root, 0)


def find_first(
    predicate: Callable[[AxNode], bool],
    *,
    max_depth: int = 30,
    root: Any | None = None,
) -> AxNode | None:
    """Return the first node matching predicate, or None."""
    for node in walk(root, max_depth=max_depth):
        try:
            if predicate(node):
                return node
        except Exception:
            continue
    return None


def find_all(
    predicate: Callable[[AxNode], bool],
    *,
    max_depth: int = 30,
    root: Any | None = None,
    limit: int = 0,
) -> list[AxNode]:
    """Collect nodes matching predicate; limit=0 means no cap."""
    out: list[AxNode] = []
    for node in walk(root, max_depth=max_depth):
        try:
            if predicate(node):
                out.append(node)
                if limit and len(out) >= limit:
                    break
        except Exception:
            continue
    return out


def press(element: Any) -> bool:
    """Invoke AXPress on an element when available."""
    err = AXUIElementPerformAction(element, kAXPressAction)
    return err == kAXErrorSuccess


def bring_wechat_front() -> bool:
    """Activate the WeChat app so its windows receive focus."""
    pid = find_wechat_pid()
    if pid is None:
        return False
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        return False
    return bool(app.activateWithOptions_(0))


def ax_content_usable() -> bool:
    """True when the main WeChat window exposes more than traffic-light chrome.

    Mac WeChat 4 (Chromium) often only publishes close/min/zoom buttons under
    AXWindow; without list/text nodes the GUI bridge cannot read or send.
    """
    wins = windows()
    if not wins:
        return False
    main = wins[0]
    kids = children_of(main)
    if len(kids) <= 3:
        # Typical chrome-only tree: three window buttons.
        roles = {attr_str(c, kAXRoleAttribute) for c in kids}
        if roles <= {"AXButton"} or len(kids) == 0:
            # Still search for any list/text under the app (rare builds).
            for node in walk(max_depth=8):
                role = node.role or ""
                if any(
                    key in role
                    for key in (
                        "AXList",
                        "AXTable",
                        "AXOutline",
                        "AXScrollArea",
                        "AXTextArea",
                        "AXTextField",
                    )
                ) and node.label not in ("搜索结果",):
                    if node.w > 80 and node.h > 40:
                        return True
            return False
    return True
