"""纯文本解析：会话行 / 时间行，不依赖 AX 或微信进程。"""

from __future__ import annotations

import re

TIME_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}|昨天|星期[一二三四五六日天]|"
    r"\d{1,2}月\d{1,2}日|\d{4}年\d{1,2}月\d{1,2}日)\s*$"
)
UNREAD_RE = re.compile(r"\[(\d+)条\]|(\d+)\s*$")
FLAG_PINNED = "已置顶"
FLAG_MUTED = "消息免打扰"


def parse_chat_item(raw: str) -> dict | None:
    """把会话列表一行的多行文本解析成 name / preview / unread 等字段。"""
    parts = [p.strip() for p in (raw or "").split("\n")]
    while parts and not parts[-1]:
        parts.pop()
    if not parts:
        return None
    name = parts[0]
    rest = parts[1:]

    pinned = any(FLAG_PINNED in p for p in parts)
    muted = any(FLAG_MUTED in p for p in parts)

    unread = 0
    time_text = ""
    preview_lines: list[str] = []
    for p in rest:
        if not p or p in (FLAG_PINNED, FLAG_MUTED):
            continue
        m = UNREAD_RE.search(p)
        if m and "[" in p:
            unread = int(m.group(1) or m.group(2) or 0)
            p = UNREAD_RE.sub("", p).strip()
            if not p:
                continue
        if TIME_RE.match(p) and not time_text:
            time_text = p.strip()
            continue
        preview_lines.append(p)

    return {
        "name": name,
        "last_message": " ".join(preview_lines).strip(),
        "last_time": time_text,
        "unread_count": unread,
        "pinned": pinned,
        "muted": muted,
    }


def classify_content(text: str) -> str:
    """粗分消息内容类型（text / image / voice / emotion / link / system）。"""
    t = (text or "").strip()
    if not t:
        return "text"
    if t in ("[图片]", "[Image]"):
        return "image"
    if t in ("[语音]", "[Voice]"):
        return "voice"
    if t.startswith("[动画表情]") or t in ("[表情]", "[Sticker]"):
        return "emotion"
    if t.startswith("[链接]") or t.startswith("[Link]"):
        return "link"
    if t.startswith("你撤回了一条消息") or t.startswith("撤回了一条消息"):
        return "system"
    return "text"


def is_time_row(text: str) -> bool:
    """判断一行是否为消息列表里的时间分隔。"""
    return bool(TIME_RE.match((text or "").strip()))
