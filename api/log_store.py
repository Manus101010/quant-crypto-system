"""In-memory terminal log — circular buffer, thread-safe."""
from __future__ import annotations
from collections import deque
from datetime import datetime
import threading

_log: deque[dict] = deque(maxlen=120)
_lock = threading.Lock()


def log(level: str, message: str) -> None:
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "level": level,   # ok | info | warn | err
        "message": message,
    }
    with _lock:
        _log.appendleft(entry)


def get_logs(n: int = 30) -> list[dict]:
    with _lock:
        return list(_log)[:n]


def ok(msg: str)   -> None: log("ok",   msg)
def info(msg: str) -> None: log("info", msg)
def warn(msg: str) -> None: log("warn", msg)
def err(msg: str)  -> None: log("err",  msg)
