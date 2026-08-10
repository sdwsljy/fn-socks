# -*- coding: utf-8 -*-
"""SSD (ShadowsocksD) 订阅解析：ssd://base64(JSON)。"""
import json

from . import helpers
from .links import make_node


def parse_ssd(rest):
    dec = helpers.b64decode_str(rest)
    if not dec:
        return None
    try:
        data = json.loads(dec)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    servers = data.get("servers")
    if not isinstance(servers, list):
        return None
    default_port = data.get("port")
    default_method = data.get("encryption")
    default_password = data.get("password")
    default_group = data.get("airport") or ""
    nodes = []
    for s in servers:
        if not isinstance(s, dict):
            continue
        server = str(s.get("server") or "")
        port = s.get("port") or default_port
        method = s.get("encryption") or default_method
        password = s.get("password") or default_password
        try:
            port = int(port)
        except (TypeError, ValueError):
            continue
        if not server or not port or not method or password is None:
            continue
        data_d = {"method": method, "password": password}
        plugin = s.get("plugin")
        if plugin:
            data_d["plugin"] = plugin
        if s.get("plugin_opts"):
            data_d["plugin_opts"] = s["plugin_opts"]
        nodes.append(make_node("ss", str(s.get("remarks") or ""), server, port, data_d))
    return nodes
