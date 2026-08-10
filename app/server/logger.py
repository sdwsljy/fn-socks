# -*- coding: utf-8 -*-
"""线程安全的文件日志器（同时输出到控制台），带简单大小轮转。"""
import os
import threading
import time

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}
DEFAULT_LEVEL = "info"
MAX_BYTES = 2 * 1024 * 1024


class Logger(object):
    def __init__(self, log_file=None, level="info", tag="app"):
        self._lock = threading.Lock()
        self._file = log_file
        self._tag = tag
        self._level = _LEVELS.get(str(level).lower(), 20)
        if self._file:
            d = os.path.dirname(self._file)
            if d:
                os.makedirs(d, exist_ok=True)

    def set_level(self, level):
        self._level = _LEVELS.get(str(level).lower(), 20)

    def _rotate(self):
        if not self._file:
            return
        try:
            if os.path.getsize(self._file) > MAX_BYTES:
                bak = self._file + ".1"
                try:
                    os.replace(self._file, bak)
                except Exception:
                    os.remove(self._file)
        except Exception:
            pass

    def _write(self, level, msg):
        with self._lock:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            line = "[%s][%s][%s] %s" % (ts, self._tag, level.upper(), msg)
            try:
                print(line)
            except Exception:
                pass
            if self._file:
                self._rotate()
                try:
                    with open(self._file, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception:
                    pass

    def debug(self, msg):
        if self._level <= 10:
            self._write("debug", msg)

    def info(self, msg):
        if self._level <= 20:
            self._write("info", msg)

    def warn(self, msg):
        if self._level <= 30:
            self._write("warn", msg)

    def error(self, msg):
        if self._level <= 40:
            self._write("error", msg)


_loggers = {}
_loggers_lock = threading.Lock()


def get_logger(log_file=None, level=DEFAULT_LEVEL, tag="app"):
    with _loggers_lock:
        key = (log_file, tag)
        if key not in _loggers:
            _loggers[key] = Logger(log_file, level, tag)
        return _loggers[key]


def tail_log(log_file, lines=200):
    if not log_file or not os.path.isfile(log_file):
        return []
    try:
        with open(log_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = min(size, 64 * 1024)
            f.seek(size - chunk)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        parts = text.splitlines()
        return parts[-lines:]
    except Exception:
        return []
