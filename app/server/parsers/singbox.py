# -*- coding: utf-8 -*-
"""sing-box JSON 订阅解析（订阅内容为 outbounds 数组或完整配置 JSON）。"""
import json

from .links import make_node


def _to_node(ob):
    if not isinstance(ob, dict):
        return None
    otype = str(ob.get("type") or "").lower()
    if otype in ("", "selector", "urltest", "loadbalance", "block", "dns", "wireguard", "tor", "ssh"):
        return None
    server = str(ob.get("server") or "")
    try:
        port = int(ob.get("server_port") or 0)
    except (TypeError, ValueError):
        port = 0
    if not server or not port:
        return None
    name = str(ob.get("tag") or "") or ("%s:%s" % (server, port))
    data = {"outbound": ob}
    if otype == "shadowsocks":
        ptype = "ss"
    elif otype == "shadowsocksr":
        ptype = "ssr"
    else:
        ptype = otype
    return make_node(ptype, name, server, port, data)


def parse_singbox(text):
    text = text.strip()
    if not (text.startswith("{") or text.startswith("[")):
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    outbounds = None
    if isinstance(data, list):
        outbounds = data
    elif isinstance(data, dict):
        outbounds = data.get("outbounds")
    if not isinstance(outbounds, list):
        return None
    nodes = []
    for ob in outbounds:
        node = _to_node(ob)
        if node:
            nodes.append(node)
    return nodes
