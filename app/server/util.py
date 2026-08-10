# -*- coding: utf-8 -*-
"""通用工具函数：JSON 读写、原子写、时间戳、目录创建。"""
import json
import os
import tempfile
import time

try:
    from uuid import uuid4
except ImportError:  # pragma: no cover
    uuid4 = None


def now_ts():
    return int(time.time())


def new_id():
    from uuid import uuid4
    return str(uuid4())


def ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path


def read_json(path, default=None):
    if default is None:
        default = []
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    ensure_dir(os.path.dirname(path))
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path) or ".", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def deep_copy(obj):
    import copy
    return copy.deepcopy(obj)


def human_size(n):
    if n is None:
        return "-"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    if n < 0:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return "%d %s" % (int(n), units[i])
    return "%.2f %s" % (n, units[i])


def is_valid_port(port):
    try:
        p = int(port)
        return 1 <= p <= 65535
    except (TypeError, ValueError):
        return False


def gen_id():
    import uuid
    return uuid.uuid4().hex[:12]
