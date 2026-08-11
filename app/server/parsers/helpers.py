# -*- coding: utf-8 -*-
"""解析辅助：Base64 编解码（兼容 URL-safe / 缺失 padding）、链接切分等。"""
import base64
import binascii
import urllib.parse

try:
    from urllib.parse import unquote as _unquote
except ImportError:  # pragma: no cover
    from urllib import unquote as _unquote  # type: ignore


def b64decode_any(text):
    if not text:
        return None
    s = text.strip()
    s = "".join(s.split())
    if len(s) % 4 != 0:
        s += "=" * (4 - len(s) % 4)
    for variant in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return variant(s, validate=True)
        except (binascii.Error, ValueError, TypeError):
            continue
    return None


def b64decode_str(text, encoding="utf-8"):
    data = b64decode_any(text)
    if data is None:
        return None
    try:
        return data.decode(encoding, errors="replace")
    except Exception:
        return None


def b64encode_str(text, urlsafe=False):
    data = text.encode("utf-8")
    if urlsafe:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
    return base64.b64encode(data).decode("ascii").rstrip("=")


def split_link(link):
    link = link.strip()
    idx = link.find("#")
    fragment = ""
    if idx >= 0:
        fragment = link[idx + 1:]
        link = link[:idx]
    scheme = ""
    rest = link
    m = link.find("://")
    if m > 0:
        scheme = link[:m].lower()
        rest = link[m + 3:]
    return scheme, rest, _unquote(fragment)


def parse_host_port(hostport, default_port=None):
    hostport = hostport.strip()
    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            return hostport, default_port
        host = hostport[1:end]
        port = default_port
        if end + 1 < len(hostport) and hostport[end + 1] == ":":
            p = hostport[end + 2:]
            try:
                port = int(p)
            except ValueError:
                port = default_port
        return host, _clamp_port(port, default_port)
    if ":" in hostport:
        host, _, p = hostport.rpartition(":")
        if host == "":
            host = hostport
        try:
            port = int(p)
        except ValueError:
            return hostport, default_port
        return host, _clamp_port(port, default_port)
    return hostport, default_port


def _clamp_port(port, default_port):
    """端口范围校验：超出 [1, 65535] 视为非法，回落到 default_port。"""
    if port is None:
        return default_port
    try:
        p = int(port)
    except (TypeError, ValueError):
        return default_port
    if 1 <= p <= 65535:
        return p
    return default_port


def qs_get(params, key, default=None):
    v = params.get(key)
    if v is None:
        return default
    if isinstance(v, list):
        v = v[0] if v else default
    return v


def strip_scheme(link):
    m = link.find("://")
    if m > 0:
        return link[m + 3:]
    return link
