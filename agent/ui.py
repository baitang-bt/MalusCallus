"""全局 UI 操作锁。

微信界面与辅助功能树是单线程资源：gRPC worker 与登录轮询不能并发点按/打字。
用 RLock，便于操作级函数再调用底层 click / type。
"""
from __future__ import annotations

import threading
from functools import wraps

UI_LOCK = threading.RLock()


def synchronized(fn):
    """把函数整体放进 UI 锁里，避免并发 SendText 键码交错。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        with UI_LOCK:
            return fn(*args, **kwargs)

    return wrapper


__all__ = ["UI_LOCK", "synchronized"]
