"""Unit tests for preview sender splitting."""

from agent.sender_name import is_plausible_sender_name, split_preview_sender


def test_split_preview_sender() -> None:
    """Nickname: body splits; bracket labels are rejected as senders."""
    sender, body = split_preview_sender("小明: 你好啊")
    assert sender == "小明"
    assert body == "你好啊"
    sender, body = split_preview_sender("[链接] 标题: 摘要")
    assert sender == ""
    assert "链接" in body or "标题" in body


def test_plausible_sender() -> None:
    """Bracket heads are not plausible nicknames."""
    assert is_plausible_sender_name("小明")
    assert not is_plausible_sender_name("[链接]")
