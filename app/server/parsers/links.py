# -*- coding: utf-8 -*-
"""URI 分享链接解析：ss / ssr / vmess / vless / trojan / hysteria2 / tuic / socks5。

参考 PassWall2 subscribe.lua 的解析思路与 Xray-core 链接格式规范。
"""
import json
import urllib.parse

from . import helpers


def make_node(ptype, name, server, port, data):
    return {
        "name": (name or "").strip() or "%s:%s" % (server or "?", port or "?"),
        "type": ptype,
        "server": server or "",
        "port": int(port) if port else 0,
        "data": data or {},
    }


def parse_ss(rest, fragment=""):
    userinfo = None
    hostport = None
    query = ""
    if "?" in rest:
        rest, _, query = rest.partition("?")
    if "@" in rest:
        userinfo, _, hostport = rest.rpartition("@")
    else:
        dec = helpers.b64decode_str(rest)
        if dec and "@" in dec:
            userinfo, _, hostport = dec.rpartition("@")
        else:
            return None

    method = None
    password = None
    if ":" in userinfo:
        dec = helpers.b64decode_str(userinfo)
        if dec and ":" in dec and not dec.startswith(("http", "https")):
            method, _, password = dec.partition(":")
        else:
            method, _, password = userinfo.partition(":")
    elif userinfo:
        dec = helpers.b64decode_str(userinfo)
        if dec and ":" in dec:
            method, _, password = dec.partition(":")

    if not method or password is None:
        return None
    host, port = helpers.parse_host_port(hostport)
    if not host or not port:
        return None

    data = {"method": method, "password": password}
    if query:
        qs = urllib.parse.parse_qs(query)
        plugin = helpers.qs_get(qs, "plugin")
        if plugin:
            data["plugin"] = plugin
    return make_node("ss", fragment, host, port, data)


def parse_ssr(rest, fragment=""):
    dec = helpers.b64decode_str(rest)
    if not dec:
        return None
    main, _, query = dec.partition("/?")
    parts = main.split(":")
    if len(parts) < 6:
        return None
    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        return None
    protocol, method, obfs = parts[2], parts[3], parts[4]
    password = helpers.b64decode_str(parts[5]) or parts[5]
    data = {
        "method": method,
        "password": password,
        "protocol": protocol,
        "obfs": obfs,
    }
    if query:
        qs = urllib.parse.parse_qs(query)
        obfsparam = helpers.qs_get(qs, "obfsparam", "")
        protoparam = helpers.qs_get(qs, "protoparam", "")
        group = helpers.qs_get(qs, "group", "")
        remarks = helpers.qs_get(qs, "remarks", "")
        data["obfs_param"] = helpers.b64decode_str(obfsparam) or obfsparam
        data["protocol_param"] = helpers.b64decode_str(protoparam) or protoparam
        if not fragment:
            fragment = helpers.b64decode_str(remarks) or remarks
        if group:
            data["group"] = helpers.b64decode_str(group) or group
    return make_node("ssr", fragment, host, port, data)


def _g(src, key, default=None):
    v = src.get(key)
    if v is None:
        return default
    if isinstance(v, list):
        v = v[0] if v else default
    return v


def _vmess_transport(net, vm):
    data = {"network": net or "tcp"}
    host = _g(vm, "host") or _g(vm, "Host")
    path = _g(vm, "path") or ""
    if net in ("ws", "http", "h2", "httpupgrade"):
        if host:
            data["host"] = host
        if path:
            data["path"] = path
    elif net == "grpc":
        svc = _g(vm, "serviceName") or _g(vm, "path") or ""
        if svc:
            data["service_name"] = svc
    elif net in ("kcp", "mkcp"):
        data["head_type"] = _g(vm, "type") or "none"
        seed = _g(vm, "path") or _g(vm, "seed")
        if seed:
            data["seed"] = seed
    elif net == "quic":
        data["quic_security"] = _g(vm, "host") or "none"
        data["quic_key"] = _g(vm, "path") or ""
        data["head_type"] = _g(vm, "type") or "none"
    tls = str(_g(vm, "tls") or _g(vm, "security") or "").lower()
    if tls in ("1", "true", "tls"):
        data["tls"] = True
        sni = _g(vm, "sni") or host or ""
        if sni:
            data["sni"] = sni
        fp = _g(vm, "fp")
        if fp:
            data["fp"] = fp
        alpn = _g(vm, "alpn")
        if alpn:
            data["alpn"] = alpn if isinstance(alpn, list) else [alpn]
    return data


def parse_vmess(rest, fragment=""):
    data = {}
    if "@" not in rest:
        dec = helpers.b64decode_str(rest)
        if not dec:
            return None
        try:
            vm = json.loads(dec)
        except (ValueError, TypeError):
            return None
        if not isinstance(vm, dict) or "add" not in vm:
            return None
        host = str(vm.get("add") or "")
        try:
            port = int(vm.get("port") or 0)
        except (TypeError, ValueError):
            return None
        if not host or not port:
            return None
        name = fragment or str(vm.get("ps") or "")
        data = {
            "uuid": str(vm.get("id") or ""),
            "security": str(vm.get("scy") or "auto") or "auto",
            "alter_id": int(vm.get("aid") or 0),
        }
        data.update(_vmess_transport(str(vm.get("net") or "tcp").lower(), vm))
        return make_node("vmess", name, host, port, data)

    userinfo, _, hostport = rest.rpartition("@")
    qs = {}
    if "?" in hostport:
        hostport, _, q = hostport.partition("?")
        qs = urllib.parse.parse_qs(q)
    host, port = helpers.parse_host_port(hostport)
    if not host or not port or not userinfo:
        return None
    data = {
        "uuid": userinfo,
        "security": "auto",
        "alter_id": 0,
    }
    data.update(_vmess_transport(helpers.qs_get(qs, "type", "tcp"), qs))
    return make_node("vmess", fragment, host, port, data)


def parse_vless(rest, fragment=""):
    userinfo, _, hostport = rest.rpartition("@")
    qs = {}
    if "?" in hostport:
        hostport, _, q = hostport.partition("?")
        qs = urllib.parse.parse_qs(q)
    host, port = helpers.parse_host_port(hostport)
    if not host or not port or not userinfo:
        return None
    data = {"uuid": userinfo}
    flow = helpers.qs_get(qs, "flow")
    if flow:
        data["flow"] = flow
    data.update(_vmess_transport(helpers.qs_get(qs, "type", "tcp"), qs))
    security = helpers.qs_get(qs, "security", "").lower()
    if security in ("tls", "xtls", "reality"):
        data["tls"] = True
        if security == "reality":
            data["reality"] = True
        elif security == "xtls":
            data["xtls"] = True
        sni = helpers.qs_get(qs, "sni") or helpers.qs_get(qs, "host") or ""
        if sni:
            data["sni"] = sni
        for k in ("fp", "pbk", "sid", "spx"):
            v = helpers.qs_get(qs, k)
            if v:
                data[k] = v
        alpn = helpers.qs_get(qs, "alpn")
        if alpn:
            data["alpn"] = alpn.split(",") if "," in alpn else [alpn]
    insecure = helpers.qs_get(qs, "allowInsecure", "0")
    if str(insecure) in ("1", "true"):
        data["allow_insecure"] = True
    return make_node("vless", fragment, host, port, data)


def parse_trojan(rest, fragment=""):
    userinfo, _, hostport = rest.rpartition("@")
    qs = {}
    if "?" in hostport:
        hostport, _, q = hostport.partition("?")
        qs = urllib.parse.parse_qs(q)
    host, port = helpers.parse_host_port(hostport)
    if not host or not port or userinfo is None:
        return None
    data = {"password": userinfo}
    data.update(_vmess_transport(helpers.qs_get(qs, "type", "tcp"), qs))
    if not data.get("sni"):
        sni = helpers.qs_get(qs, "sni")
        if sni:
            data["sni"] = sni
    insecure = helpers.qs_get(qs, "allowInsecure", "0")
    if str(insecure) in ("1", "true"):
        data["allow_insecure"] = True
    fp = helpers.qs_get(qs, "fp")
    if fp:
        data["fp"] = fp
    alpn = helpers.qs_get(qs, "alpn")
    if alpn:
        data["alpn"] = alpn.split(",") if "," in alpn else [alpn]
    return make_node("trojan", fragment, host, port, data)


def parse_hysteria2(rest, fragment=""):
    userinfo, _, hostport = rest.rpartition("@")
    qs = {}
    if "?" in hostport:
        hostport, _, q = hostport.partition("?")
        qs = urllib.parse.parse_qs(q)
    host, port = helpers.parse_host_port(hostport)
    if not host or not port:
        return None
    data = {"password": userinfo or ""}
    sni = helpers.qs_get(qs, "sni") or host
    if sni:
        data["sni"] = sni
    if helpers.qs_get(qs, "insecure", "0") in ("1", "true"):
        data["insecure"] = True
    alpn = helpers.qs_get(qs, "alpn")
    if alpn:
        data["alpn"] = alpn.split(",") if "," in alpn else [alpn]
    return make_node("hysteria2", fragment, host, port, data)


def parse_tuic(rest, fragment=""):
    userinfo, _, hostport = rest.rpartition("@")
    qs = {}
    if "?" in hostport:
        hostport, _, q = hostport.partition("?")
        qs = urllib.parse.parse_qs(q)
    host, port = helpers.parse_host_port(hostport)
    if not host or not port or not userinfo:
        return None
    uuid = userinfo
    password = ""
    if ":" in userinfo:
        uuid, _, password = userinfo.partition(":")
    data = {"uuid": uuid, "password": password}
    cc = helpers.qs_get(qs, "congestion_control", "bbr")
    if cc:
        data["congestion_control"] = cc
    alpn = helpers.qs_get(qs, "alpn")
    if alpn:
        data["alpn"] = alpn.split(",") if "," in alpn else [alpn]
    sni = helpers.qs_get(qs, "sni")
    if sni:
        data["sni"] = sni
    udp = helpers.qs_get(qs, "udp_relay_mode")
    if udp:
        data["udp_relay_mode"] = udp
    if helpers.qs_get(qs, "allow_insecure", "0") in ("1", "true"):
        data["insecure"] = True
    return make_node("tuic", fragment, host, port, data)


def parse_socks(rest, fragment=""):
    userinfo = ""
    hostport = rest
    if "@" in rest:
        userinfo, _, hostport = rest.rpartition("@")
    host, port = helpers.parse_host_port(hostport)
    if not host or not port:
        return None
    data = {"version": "5"}
    if ":" in userinfo:
        u, _, p = userinfo.partition(":")
        data["username"] = u
        data["password"] = p
    elif userinfo:
        data["username"] = userinfo
    return make_node("socks", fragment, host, port, data)


_SCHEMES = {
    "ss": parse_ss,
    "ssr": parse_ssr,
    "vmess": parse_vmess,
    "vless": parse_vless,
    "trojan": parse_trojan,
    "hysteria2": parse_hysteria2,
    "hysteria": parse_hysteria2,
    "hy2": parse_hysteria2,
    "tuic": parse_tuic,
    "socks": parse_socks,
    "socks5": parse_socks,
}


def parse_link(line):
    if not line:
        return None
    line = line.strip()
    if not line:
        return None
    scheme, rest, fragment = helpers.split_link(line)
    handler = _SCHEMES.get(scheme)
    if handler is None:
        return None
    try:
        node = handler(rest, fragment)
        if node is None:
            return None
        node["raw"] = line
        return node
    except Exception:
        return None


def parse_links(text):
    nodes = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        node = parse_link(line)
        if node:
            nodes.append(node)
    return nodes
