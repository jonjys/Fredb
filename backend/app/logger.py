"""Logging setup: console + rotating file + in-memory ring buffer for the dashboard."""
from __future__ import annotations

import logging
import logging.handlers
import os
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Deque, List


@dataclass
class LogEntry:
    timestamp: float
    level: str
    message: str
    logger_name: str = ""


class LogBuffer:
    """Thread-safe ring buffer of recent log lines, polled by the dashboard."""

    def __init__(self, maxlen: int = 500):
        self._buf: Deque[LogEntry] = deque(maxlen=maxlen)
        self._lock = Lock()

    def add(self, level: str, message: str, logger_name: str = "") -> None:
        with self._lock:
            self._buf.append(
                LogEntry(timestamp=time.time(), level=level, message=message, logger_name=logger_name)
            )

    def recent(self, limit: int = 200, logger_prefix: str = "") -> List[LogEntry]:
        with self._lock:
            items = list(self._buf)
        if logger_prefix:
            items = [e for e in items if e.logger_name.startswith(logger_prefix)]
        return items[-limit:]


log_buffer = LogBuffer()


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_buffer.add(record.levelname, self.format(record), logger_name=record.name)
        except Exception:
            pass


def setup_logging(level: str = "INFO") -> logging.Logger:
    os.makedirs("data", exist_ok=True)
    logger = logging.getLogger("tradingbot")
    logger.setLevel(level)
    if logger.handlers:
        return logger  # already configured (e.g. reload)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        "data/bot.log", maxBytes=5_000_000, backupCount=3
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    buffer_handler = BufferHandler()
    buffer_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(buffer_handler)

    logger.propagate = False
    return logger
