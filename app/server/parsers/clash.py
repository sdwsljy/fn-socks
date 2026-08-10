# -*- coding: utf-8 -*-
"""Clash YAML 订阅解析：把 proxies 列表映射为统一节点模型。"""
from . import mini_yaml
from .links import make_node

_TYPE_MAP = {
    "ss": "ss",
    "ssr": "ssr",
    "vmess": "vmess",
    "vless": "vless",
    "trojan": "trojan",
    "hysteria2": "hysteria2",
    "tuic": "tuic",
    "socks5": "socks",
    "socks": "socks",
    "http": "http",
    "wireguard": "wireguard",
    "snell": "snell",
    "anytls": "anytls",
}


def _clash_ws_opts(p, data):
    ws = p.get("ws-opts") or {}
    if isinstance(ws, dict):
        path = ws.get("path")
        if path:
            data["path"] = str(path)
        headers = ws.get("headers")
        if isinstance(headers, dict):
            host = headers.get("Host")
            if host:
                data["host"] = str(host)
    elif ws:
        data["path"] = str(ws)


def _clash_h2_opts(p, data):
    h2 = p.get("h2-opts") or {}
    if isinstance(h2, dict):
        host = h2.get("host")
        if host:
            data["host"] = host if isinstance(host, list) else str(host)
        path = h2.get("path")
        if path:
            data["path"] = str(path)
    elif h2:
        data["host"] = str(h2)


def _clash_grpc_opts(p, data):
    g = p.get("grpc-opts") or {}
    if isinstance(g, dict):
        svc = g.get("grpc-service-name")
        if svc:
            data["service_name"] = str(svc)
    elif g:
        data["service_name"] = str(g)


def _clash_transport(p, data):
    network = str(p.get("network") or "tcp").lower()
    data["network"] = network
    if network in ("ws", "http", "httpupgrade", "h2"):
        _clash_ws_opts(p, data)
        if network == "h2":
            _clash_h2_opts(p, data)
    elif network == "grpc":
        _clash_grpc_opts(p, data)
    elif network in ("kcp", "mkcp"):
        data["head_type"] = str(p.get("kcp-opts", {}).get("header", {}).get("type", "none")) \
            if isinstance(p.get("kcp-opts"), dict) else "none"
    tls = p.get("tls")
    if tls is True or str(tls).lower() in ("1", "true"):
        data["tls"] = True
        servername = p.get("servername") or p.get("sni") or ""
        if servername:
            data["sni"] = str(servername)
        fp = p.get("client-fingerprint") or p.get("fp")
        if fp:
            data["fp"] = str(fp)
        alpn = p.get("alpn")
        if isinstance(alpn, list) and alpn:
            data["alpn"] = [str(x) for x in alpn]
        reality = p.get("reality-opts") or {}
        if isinstance(reality, dict):
            pk = reality.get("public-key")
            sid = reality.get("short-id")
            if pk:
                data["reality"] = True
                data["pbk"] = str(pk)
            if sid:
                data["sid"] = str(sid)
        if p.get("skip-cert-verify"):
            data["allow_insecure"] = True


def parse_clash_proxy(p):
    if not isinstance(p, dict):
        return None
    ctype = str(p.get("type") or "").lower()
    ptype = _TYPE_MAP.get(ctype)
    if ptype is None:
        return None
    server = str(p.get("server") or "")
    try:
        port = int(p.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if not server or not port:
        return None
    name = str(p.get("name") or "") or ("%s:%s" % (server, port))
    data = {}

    if ptype == "ss":
        data.update({"method": str(p.get("cipher") or ""), "password": str(p.get("password") or "")})
        plugin = p.get("plugin")
        if plugin:
            data["plugin"] = str(plugin)
        opts = p.get("plugin-opts")
        if opts and isinstance(opts, dict):
            mode = opts.get("mode")
            host = opts.get("host")
            tls = opts.get("tls")
            if mode:
                data["plugin_opts"] = "mode=%s" % mode
            if host:
                data["plugin_opts"] = (data.get("plugin_opts", "") + ";host=%s" % host).strip(";")
            if tls:
                data["plugin_opts"] = (data.get("plugin_opts", "") + ";tls").strip(";")
    elif ptype == "ssr":
        data.update({
            "method": str(p.get("cipher") or ""),
            "password": str(p.get("password") or ""),
            "protocol": str(p.get("protocol") or ""),
            "protocol_param": str(p.get("protocol-param") or ""),
            "obfs": str(p.get("obfs") or ""),
            "obfs_param": str(p.get("obfs-param") or ""),
        })
    elif ptype == "vmess":
        data.update({
            "uuid": str(p.get("uuid") or ""),
            "security": str(p.get("cipher") or "auto") or "auto",
            "alter_id": int(p.get("alterId") or 0),
        })
        _clash_transport(p, data)
    elif ptype == "vless":
        data["uuid"] = str(p.get("uuid") or "")
        flow = p.get("flow")
        if flow:
            data["flow"] = str(flow)
        _clash_transport(p, data)
        if str(p.get("tls", "")).lower() == "reality":
            data["reality"] = True
    elif ptype == "trojan":
        data["password"] = str(p.get("password") or "")
        _clash_transport(p, data)
    elif ptype == "hysteria2":
        data["password"] = str(p.get("password") or "")
        sni = p.get("sni") or server
        data["sni"] = str(sni)
        if p.get("skip-cert-verify"):
            data["insecure"] = True
        alpn = p.get("alpn")
        if isinstance(alpn, list) and alpn:
            data["alpn"] = [str(x) for x in alpn]
    elif ptype == "tuic":
        data.update({
            "uuid": str(p.get("uuid") or ""),
            "password": str(p.get("password") or ""),
        })
        cc = p.get("congestion-controller")
        if cc:
            data["congestion_control"] = str(cc)
        sni = p.get("sni")
        if sni:
            data["sni"] = str(sni)
        alpn = p.get("alpn")
        if isinstance(alpn, list) and alpn:
            data["alpn"] = [str(x) for x in alpn]
        if p.get("skip-cert-verify"):
            data["insecure"] = True
    elif ptype == "socks":
        data["version"] = "5"
        if p.get("username"):
            data["username"] = str(p.get("username"))
        if p.get("password"):
            data["password"] = str(p.get("password"))
    elif ptype == "http":
        data["version"] = "1.1"
        if p.get("username"):
            data["username"] = str(p.get("username"))
        if p.get("password"):
            data["password"] = str(p.get("password"))
    elif ptype in ("wireguard", "snell", "anytls"):
        data["unsupported"] = True
        data["extra"] = dict(p)

    node = make_node(ptype, name, server, port, data)
    return node


def parse_clash(text):
    proxies = mini_yaml.extract_proxies(text)
    if proxies is None:
        return None
    nodes = []
    for p in proxies:
        node = parse_clash_proxy(p)
        if node:
            nodes.append(node)
    return nodes
