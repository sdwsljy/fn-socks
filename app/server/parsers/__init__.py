# -*- coding: utf-8 -*-
"""订阅文本解析入口：自动识别 ssd / Clash YAML / sing-box JSON / base64 链接。"""
from . import clash, links, singbox, ssd
from .helpers import b64decode_any, b64decode_str
from .links import parse_link, parse_links


def _looks_like_yaml(text):
    for line in text.splitlines():
        ls = line.strip()
        if ls.startswith("proxies:") or ls.startswith("proxy-providers:"):
            return True
        if ls.startswith("mixed-port:") or ls.startswith("socks-port:"):
            return True
        if ls.startswith("port:") and ":" in ls.split(":", 1)[1]:
            return True
    return False


def parse_subscription_text(text):
    """解析订阅内容，返回 (nodes, fmt, parsed_count, failed_count)。

    格式优先级：SSD > YAML(Clash) > sing-box JSON > base64/明文链接。
    """
    text = text or ""
    text = text.strip()
    if not text:
        return [], "empty", 0, 0

    if text.startswith("ssd://"):
        nodes = ssd.parse_ssd(text[len("ssd://"):])
        if nodes is not None:
            return nodes, "ssd", len(nodes), 0

    if _looks_like_yaml(text) or text.lstrip().startswith(("proxies:", "mixed-port:")):
        nodes = clash.parse_clash(text)
        if nodes is not None:
            return nodes, "clash", len(nodes), 0

    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        nodes = singbox.parse_singbox(text)
        if nodes is not None:
            return nodes, "sing-box", len(nodes), 0

    content = text
    decoded = b64decode_str(text)
    if decoded and decoded.strip():
        content = decoded
    raw_lines = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("//"):
            raw_lines.append(line)

    joined = "\n".join(raw_lines)
    if raw_lines and (len(raw_lines) == 1):
        single = raw_lines[0]
        if single.startswith("[") or single.startswith("{"):
            nodes = singbox.parse_singbox(single)
            if nodes is not None:
                return nodes, "sing-box", len(nodes), 0
        if single.startswith("ssd://"):
            nodes = ssd.parse_ssd(single[len("ssd://"):])
            if nodes is not None:
                return nodes, "ssd", len(nodes), 0

    nodes = links.parse_links("\n".join(raw_lines))
    total = len(raw_lines)
    failed = max(total - len(nodes), 0)
    return nodes, "uri", len(nodes), failed


def parse_links_text(text):
    return links.parse_links(text or "")
