# -*- coding: utf-8 -*-
"""sing-box 配置生成：mixed 入站（SOCKS5/HTTP）+ 节点出站，支持每代理独立节点路由。

节点统一数据模型（node["data"]）到 sing-box outbound 的映射：
  - ss      : method / password / plugin / plugin_opts
  - ssr     : method / password / obfs / obfs_param / protocol / protocol_param
  - vmess   : uuid / security / alter_id / network / host / path / service_name / tls / sni / fp / alpn
  - vless   : uuid / flow / security / reality / pbk / sid / spx / tls / sni / fp / alpn / network / host / path / service_name
  - trojan  : password / tls / sni / fp / alpn / network / host / path / service_name / allow_insecure
  - hysteria2 : password / sni / insecure / alpn
  - tuic    : uuid / password / congestion_control / alpn / sni / udp_relay_mode / insecure
  - socks   : username / password / version
"""
import copy
import json


def node_to_outbound(node):
    ntype = (node.get("type") or "").lower()
    data = node.get("data") or {}
    server = node.get("server") or data.get("server") or ""
    port = node.get("port") or data.get("server_port") or 0
    if not server or not port:
        raise ValueError("节点缺少服务器地址或端口")

    if ntype == "ss":
        ob = {
            "type": "shadowsocks",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "method": data.get("method") or "aes-256-gcm",
            "password": data.get("password") or "",
        }
        plugin = data.get("plugin")
        if plugin:
            ob["plugin"] = plugin
            ob["plugin_opts"] = data.get("plugin_opts") or ""
    elif ntype == "ssr":
        ob = {
            "type": "shadowsocksr",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "method": data.get("method") or "",
            "password": data.get("password") or "",
            "obfs": data.get("obfs") or "plain",
            "obfs_param": data.get("obfs_param") or "",
            "protocol": data.get("protocol") or "origin",
            "protocol_param": data.get("protocol_param") or "",
        }
    elif ntype == "vmess":
        ob = {
            "type": "vmess",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "uuid": data.get("uuid") or "",
            "security": data.get("security") or "auto",
            "alter_id": int(data.get("alter_id") or 0),
        }
        _apply_transport(ob, data)
        _apply_tls(ob, data, tls_value=data.get("tls"))
    elif ntype == "vless":
        ob = {
            "type": "vless",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "uuid": data.get("uuid") or "",
        }
        if data.get("flow"):
            ob["flow"] = data["flow"]
        if data.get("xtls"):
            ob["flow"] = data.get("flow") or "xtls-rprx-vision"
        _apply_transport(ob, data)
        _apply_tls(ob, data, reality=data.get("reality"))
    elif ntype == "trojan":
        ob = {
            "type": "trojan",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "password": data.get("password") or "",
        }
        _apply_transport(ob, data)
        _apply_tls(ob, data, tls_value=True)
    elif ntype == "hysteria2":
        tls = {
            "enabled": True,
            "server_name": data.get("sni") or server,
            "insecure": bool(data.get("insecure")),
        }
        if data.get("alpn"):
            tls["alpn"] = data["alpn"]
        ob = {
            "type": "hysteria2",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "password": data.get("password") or "",
            "tls": tls,
        }
    elif ntype == "tuic":
        tls = {
            "enabled": True,
            "server_name": data.get("sni") or server,
            "insecure": bool(data.get("insecure")),
        }
        if data.get("alpn"):
            tls["alpn"] = data["alpn"]
        ob = {
            "type": "tuic",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "uuid": data.get("uuid") or "",
            "password": data.get("password") or "",
            "congestion_control": data.get("congestion_control") or "bbr",
            "tls": tls,
        }
        if data.get("udp_relay_mode"):
            ob["udp_relay_mode"] = data["udp_relay_mode"]
    elif ntype == "socks":
        ob = {
            "type": "socks",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
            "version": data.get("version") or "5",
        }
        if data.get("username"):
            ob["username"] = data["username"]
        if data.get("password"):
            ob["password"] = data["password"]
    elif ntype == "http":
        ob = {
            "type": "http",
            "tag": "proxy",
            "server": server,
            "server_port": int(port),
        }
        if data.get("username"):
            ob["username"] = data["username"]
        if data.get("password"):
            ob["password"] = data["password"]
    elif data.get("outbound") and isinstance(data["outbound"], dict):
        ob = copy.deepcopy(data["outbound"])
        ob["tag"] = "proxy"
        ob["server"] = server
        ob["server_port"] = int(port)
    else:
        raise ValueError("暂不支持该节点类型: %s" % ntype)

    return ob


def _apply_transport(ob, data):
    network = (data.get("network") or "tcp").lower()
    if network in ("", "tcp"):
        return
    if network == "ws":
        ws = {}
        if data.get("path"):
            ws["path"] = data["path"]
        if data.get("host"):
            ws["headers"] = {"Host": data["host"]}
        ob["transport"] = {"type": "ws", **ws}
    elif network in ("http", "httpupgrade"):
        hu = {}
        if data.get("host"):
            hu["host"] = data["host"]
        if data.get("path"):
            hu["path"] = data["path"]
        ob["transport"] = {"type": "httpupgrade", **hu}
    elif network in ("h2", "http2"):
        h2 = {}
        if data.get("host"):
            h2["host"] = [data["host"]] if isinstance(data["host"], str) else data["host"]
        if data.get("path"):
            h2["path"] = data["path"]
        ob["transport"] = {"type": "http", **h2}
    elif network == "grpc":
        grpc = {}
        if data.get("service_name"):
            grpc["service_name"] = data["service_name"]
        ob["transport"] = {"type": "grpc", **grpc}
    elif network in ("kcp", "mkcp"):
        kcp = {}
        ht = data.get("head_type") or "none"
        if ht:
            kcp["header"] = {"type": ht}
        if data.get("seed"):
            kcp["seed"] = data["seed"]
        ob["transport"] = {"type": "kcp", **kcp}
    else:
        ob["transport"] = {"type": network}


def _apply_tls(ob, data, tls_value=None, reality=False):
    tls_enabled = bool(tls_value) or bool(reality) or bool(data.get("sni")) or bool(data.get("pbk"))
    if not tls_enabled:
        return
    tls = {"enabled": True}
    if data.get("sni"):
        tls["server_name"] = data["sni"]
    elif data.get("host") and isinstance(data["host"], str):
        tls["server_name"] = data["host"]
    insecure = data.get("allow_insecure") or data.get("insecure")
    if insecure:
        tls["insecure"] = True
    if data.get("alpn"):
        tls["alpn"] = data["alpn"]
    fp = data.get("fp")
    if fp and fp not in ("", "none"):
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    if reality or data.get("pbk"):
        reality_cfg = {"enabled": True}
        if data.get("pbk"):
            reality_cfg["public_key"] = data["pbk"]
        if data.get("sid"):
            reality_cfg["short_id"] = data["sid"]
        tls["reality"] = reality_cfg
    ob["tls"] = tls


def build_config(proxies_cfg, active_node, nodes=None, log_file=None):
    """生成完整 sing-box 配置（支持每条代理独立出口节点）。

    proxies_cfg 应为 list-of-dict；为兼容旧入口允许传入单 dict，
    此时若未显式声明 enabled 则默认启用，便于调用方传单条快速生成。
    重要：apply() 已对所有入口规整为 list，因此单 dict 路径不会被生产代码触及，
    此处的默认启用仅保留给历史调用/单元测试。
    """
    if isinstance(proxies_cfg, dict):
        proxies_cfg = [proxies_cfg]
        if "enabled" not in proxies_cfg[0]:
            proxies_cfg[0]["enabled"] = True
    enabled_list = [p for p in (proxies_cfg or []) if p.get("enabled")]
    nodes = nodes or []

    inbounds = []
    proxy_of_inbound = []
    for idx, p in enumerate(enabled_list):
        users = []
        if p.get("username") and p.get("password"):
            users.append({
                "username": p["username"],
                "password": p["password"],
            })
        inbound = {
            "type": "mixed",
            "tag": "mixed-in-%d" % idx,
            "listen": p.get("listen") or "0.0.0.0",
            "listen_port": int(p.get("port") or 1080),
        }
        if users:
            inbound["users"] = users
        inbounds.append(inbound)
        node = None
        nid = p.get("node_id")
        if nid:
            node = next((n for n in nodes if n.get("id") == nid), None)
        if node is None:
            node = active_node
        proxy_of_inbound.append((inbound["tag"], node))

    outbound_by_node = {}
    outbounds = []
    for _, node in proxy_of_inbound:
        if not node:
            continue
        nid = node.get("id") or ""
        if nid in outbound_by_node:
            continue
        try:
            ob = node_to_outbound(node)
        except ValueError:
            continue
        ob["tag"] = "node-%s" % nid
        outbound_by_node[nid] = ob
        outbounds.append(ob)
    outbounds.append({"type": "direct", "tag": "direct"})

    rules = []
    for tag, node in proxy_of_inbound:
        nid = (node.get("id") or "") if node else ""
        if nid in outbound_by_node:
            rules.append({"inbound": [tag], "outbound": outbound_by_node[nid]["tag"]})
        else:
            rules.append({"inbound": [tag], "outbound": "direct"})

    cfg = {
        "log": {"level": "info"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {"rules": rules, "final": "direct"},
    }
    if log_file:
        cfg["log"]["output"] = log_file
    return cfg


def config_to_json(cfg):
    return json.dumps(cfg, ensure_ascii=False, indent=2)
