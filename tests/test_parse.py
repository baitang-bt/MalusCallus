"""Unit tests for pure chat-row / content parsing (no WeChat process)."""

from agent.parse import classify_content, is_time_row, parse_chat_item


def test_parse_chat_item_basic() -> None:
    """Session rows with name, preview, and clock parse cleanly."""
    raw = "文件传输助手\n剪贴板方案验证：中文\n13:32\n"
    got = parse_chat_item(raw)
    assert got is not None
    assert got["name"] == "文件传输助手"
    assert "剪贴板" in got["last_message"]
    assert got["last_time"] == "13:32"
    assert got["unread_count"] == 0


def test_parse_chat_item_pinned_muted_unread() -> None:
    """Pinned / muted flags and [N条] unread are extracted."""
    raw = "土豆群\n已置顶\n[10条] \n某人: 你好\n15:12\n消息免打扰\n"
    got = parse_chat_item(raw)
    assert got is not None
    assert got["name"] == "土豆群"
    assert got["pinned"] is True
    assert got["muted"] is True
    assert got["unread_count"] == 10
    assert "你好" in got["last_message"]


def test_is_time_row() -> None:
    """Clock and relative day labels are time separators."""
    assert is_time_row("13:32")
    assert is_time_row("昨天")
    assert not is_time_row("你好")


def test_classify_content() -> None:
    """Placeholder media labels map to content_type strings."""
    assert classify_content("[图片]") == "image"
    assert classify_content("普通文字") == "text"
