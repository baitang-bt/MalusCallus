#!/usr/bin/env python3
"""Dump a short WeChat AX tree to stdout for selector authoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import ax, chat  # noqa: E402


def main() -> int:
    """Print trust status, pid, and a truncated AX dump."""
    print(f"trusted={ax.check_trusted()}")
    print(f"pid={ax.find_wechat_pid()}")
    wins = ax.windows()
    print(f"windows={len(wins)}")
    if not ax.check_trusted():
        print("grant Accessibility to this terminal/Python and retry", file=sys.stderr)
        return 2
    rows = chat.dump_tree_rows(only_visible=True, max_depth=12)
    print(f"nodes={len(rows)}")
    for n in rows[:400]:
        indent = "  " * int(n["depth"])
        name = (n["name"] or "")[:60]
        text = (n["text"] or "")[:60]
        print(f"{indent}{n['role']} name={name!r} text={text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
