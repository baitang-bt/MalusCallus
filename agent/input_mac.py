"""macOS 输入注入：CGEvent 点击与 Unicode 键入（不经输入法、不经剪贴板）。"""
from __future__ import annotations

import time

from Quartz import (  # type: ignore
    CGEventCreateKeyboardEvent,
    CGEventCreateMouseEvent,
    CGEventKeyboardSetUnicodeString,
    CGEventPost,
    CGEventSetFlags,
    CGEventSetIntegerValueField,
    CGPointMake,
    kCGEventFlagMaskShift,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGEventMouseMoved,
    kCGEventRightMouseDown,
    kCGEventRightMouseUp,
    kCGHIDEventTap,
    kCGKeyboardEventKeycode,
    kCGMouseButtonLeft,
    kCGMouseButtonRight,
)

from .ui import synchronized

# Virtual keycodes (USB HID / Carbon)
KEYCODE_RETURN = 36
KEYCODE_ESCAPE = 53
KEYCODE_DOWN = 125
KEYCODE_UP = 126


@synchronized
def click_at(x: float, y: float, button: int = 1, settle: float = 0.08) -> None:
    """在屏幕坐标点击；button=1 左键，button=3 右键（带微移以弹出菜单）。"""
    pt = CGPointMake(float(x), float(y))
    move = CGEventCreateMouseEvent(None, kCGEventMouseMoved, pt, kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, move)
    time.sleep(settle)

    if button == 3:
        down = CGEventCreateMouseEvent(None, kCGEventRightMouseDown, pt, kCGMouseButtonRight)
        CGEventPost(kCGHIDEventTap, down)
        time.sleep(0.12)
        pt2 = CGPointMake(float(x) + 2.0, float(y) + 2.0)
        move2 = CGEventCreateMouseEvent(None, kCGEventMouseMoved, pt2, kCGMouseButtonRight)
        CGEventPost(kCGHIDEventTap, move2)
        time.sleep(0.08)
        up = CGEventCreateMouseEvent(None, kCGEventRightMouseUp, pt2, kCGMouseButtonRight)
        CGEventPost(kCGHIDEventTap, up)
    else:
        down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, pt, kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, down)
        time.sleep(settle)
        up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, pt, kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, up)


@synchronized
def tap_key(keycode: int, shift: bool = False) -> None:
    """按下并松开一个虚拟键码。"""
    down = CGEventCreateKeyboardEvent(None, keycode, True)
    up = CGEventCreateKeyboardEvent(None, keycode, False)
    if shift:
        CGEventSetFlags(down, kCGEventFlagMaskShift)
        CGEventSetFlags(up, kCGEventFlagMaskShift)
    CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.02)
    CGEventPost(kCGHIDEventTap, up)


@synchronized
def tap_return() -> None:
    """按回车（发送消息）。"""
    tap_key(KEYCODE_RETURN)


@synchronized
def type_text(text: str) -> None:
    """逐字注入 Unicode，不经过输入法与剪贴板。"""
    for ch in text or "":
        # keycode 0 is unused; unicode string carries the character.
        down = CGEventCreateKeyboardEvent(None, 0, True)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(down, len(ch), ch)
        CGEventKeyboardSetUnicodeString(up, len(ch), ch)
        # Avoid synthesizing a real key from keycode 0 alone.
        CGEventSetIntegerValueField(down, kCGKeyboardEventKeycode, 0)
        CGEventSetIntegerValueField(up, kCGKeyboardEventKeycode, 0)
        CGEventPost(kCGHIDEventTap, down)
        time.sleep(0.01)
        CGEventPost(kCGHIDEventTap, up)
        time.sleep(0.005)
