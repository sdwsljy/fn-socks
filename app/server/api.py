# -*- coding: utf-8 -*-
"""REST API 定义：订阅 / 节点 / SOCKS 配置 / 核心管理 / 日志。"""
import socket
import threading
import urllib.parse

from . import util
from .core.manager import is_binary_path_allowed
from .logger import get_logger, tail_log
from .web import HTTPError


class AppContext(object):
    def __init__(self, store, subs, core, logger=None, core_log_path=None, app_log_path=None):
        self.store = store
        self.subs = subs
        self.core = core
        self.log = logger or get_logger(tag="api")
        self.core_log_path = core_log_path
        self.app_log_path = app_log_path
        self._test_lock = threading.Lock()


def _ok(**kw):
    data = {"ok": True}
    data.update(kw)
    return data


def _err(message, code=400):
    return {"ok": False, "error": message}


def resolve_active_node(store, settings, proxies, nodes, log=None):
    """解析全局当前节点；必要时自动选择第一个节点。

    返回 (node_dict_or_None, error_str_or_None)。
    - 无启用代理 -> (None, None)
    - 全部启用的代理都指定了 node_id -> (None, None)  不需要全局节点
    - 存在未指定 node_id 的代理但无全局节点 -> 自动选第一个节点
    - 完全没有节点 -> (None, "尚无节点：请先添加订阅并更新节点列表")
    """
    enabled_list = [p for p in (proxies or []) if p.get("enabled")]
    if not enabled_list:
        return None, None
    if not nodes:
        return None, "尚无节点：请先添加订阅并更新节点列表"
    active_id = settings.get("active_node_id")
    node = next((n for n in nodes if n.get("id") == active_id), None)
    if node:
        return node, None
    needs_global = any(not p.get("node_id") for p in enabled_list)
    if not needs_global:
        return None, None
    node = nodes[0]
    settings["active_node_id"] = node.get("id")
    store.save_settings(settings)
    if log:
        log.info("自动选择节点: %s" % (node.get("custom_name") or node.get("name") or node.get("id")))
    return node, None


def register_routes(app, ctx):
    # ---------------------------------------------------------------- 状态
    @app.route("GET", r"/api/status")
    def status(req):
        subs = ctx.store.load_subs()
        nodes = ctx.store.load_nodes()
        settings = ctx.store.load_settings()
        active_id = settings.get("active_node_id")
        active_node = None
        for n in nodes:
            if n.get("id") == active_id:
                active_node = n
                break
        core_status = ctx.core.status()
        proxies = settings.get("proxies") or []
        enabled_list = [p for p in proxies if p.get("enabled")]
        first = enabled_list[0] if enabled_list else (proxies[0] if proxies else {})
        return {
            "ok": True,
            "core": core_status,
            "socks": {
                "enabled": bool(enabled_list),
                "listen": first.get("listen") or "0.0.0.0",
                "port": int(first.get("port") or 1080),
                "username": first.get("username") or "",
                "has_password": bool(first.get("password")),
                "udp": bool(first.get("udp")),
                "proxy_count": len(proxies),
            },
            "proxies": [{
                "id": p.get("id"),
                "enabled": bool(p.get("enabled")),
                "listen": p.get("listen") or "0.0.0.0",
                "port": int(p.get("port") or 1080),
                "username": p.get("username") or "",
                "has_password": bool(p.get("password")),
                "udp": bool(p.get("udp")),
                "node_id": p.get("node_id") or "",
                "node_name": next((n.get("custom_name") or n.get("name") for n in nodes if n.get("id") == p.get("node_id")), None),
            } for p in proxies],
            "active_node": {
                "id": active_id,
                "name": (active_node.get("custom_name") or active_node.get("name")) if active_node else None,
                "type": active_node.get("type") if active_node else None,
            },
            "counts": {"subscriptions": len(subs), "nodes": len(nodes)},
        }

    # ---------------------------------------------------------------- 订阅
    @app.route("GET", r"/api/subscriptions")
    def list_subs(req):
        return _ok(subscriptions=ctx.subs.list_subs())

    @app.route("POST", r"/api/subscriptions")
    def add_sub(req):
        body = req.read_json()
        try:
            sub = ctx.subs.add_sub(
                url=str(body.get("url") or ""),
                remark=str(body.get("remark") or ""),
                user_agent=str(body.get("user_agent") or ""),
                interval_min=int(body.get("interval_min") or 0),
            )
        except ValueError as e:
            return _err(str(e))
        return _ok(subscription=sub)

    @app.route("PUT", r"/api/subscriptions/([^/]+)")
    def update_sub(req, sub_id):
        body = req.read_json()
        fields = {}
        for k in ("remark", "user_agent", "interval_min"):
            if k in body:
                fields[k] = body[k]
        if "url" in body:
            url = str(body["url"]).strip()
            try:
                u = urllib.parse.urlsplit(url)
            except Exception:
                return _err("订阅链接格式无效")
            if (u.scheme or "").lower() not in ("http", "https"):
                return _err("订阅链接必须以 http:// 或 https:// 开头")
            fields["url"] = url
        sub = ctx.subs.update_sub_meta(sub_id, **fields)
        if not sub:
            return _err("订阅不存在", 404)
        return _ok(subscription=sub)

    @app.route("DELETE", r"/api/subscriptions/([^/]+)")
    def delete_sub(req, sub_id):
        ctx.subs.delete_sub(sub_id)
        return _ok()

    @app.route("POST", r"/api/subscriptions/([^/]+)/update")
    def sub_update(req, sub_id):
        try:
            r = ctx.subs.update_sub(sub_id)
        except ValueError as e:
            return _err(str(e))
        return _ok(**r)

    @app.route("POST", r"/api/subscriptions/update_all")
    def sub_update_all(req):
        results = ctx.subs.update_all()
        ok_count = sum(1 for r in results if r.get("ok"))
        return _ok(updated=ok_count, total=len(results), results=results)

    # ---------------------------------------------------------------- 节点
    @app.route("GET", r"/api/nodes")
    def list_nodes(req):
        nodes = ctx.store.load_nodes()
        sub_id = req.get_param("sub_id")
        q = req.get_param("q", "").lower()
        group = req.get_param("group")
        if sub_id:
            nodes = [n for n in nodes if n.get("sub_id") == sub_id]
        if group:
            nodes = [n for n in nodes if n.get("group") == group]
        if q:
            nodes = [n for n in nodes if q in (n.get("name") or "").lower()
                     or q in (n.get("server") or "").lower()]
        return _ok(nodes=nodes)

    @app.route("POST", r"/api/nodes/import")
    def import_nodes(req):
        body = req.read_json()
        try:
            added = ctx.subs.import_links(
                str(body.get("text") or ""),
                str(body.get("group") or "手动导入"),
            )
        except ValueError as e:
            return _err(str(e))
        return _ok(added=added)

    @app.route("DELETE", r"/api/nodes/([^/]+)")
    def delete_node(req, node_id):
        removed = ctx.subs.delete_node(node_id)
        if not removed:
            return _err("节点不存在", 404)
        return _ok()

    @app.route("POST", r"/api/nodes/([^/]+)/select")
    def select_node(req, node_id):
        with ctx.store.transaction():
            nodes = ctx.store.load_nodes()
            if not any(n.get("id") == node_id for n in nodes):
                return _err("节点不存在", 404)
            settings = ctx.store.load_settings()
            settings["active_node_id"] = node_id
            ctx.store.save_settings(settings)
        return _ok()

    @app.route("PUT", r"/api/nodes/([^/]+)")
    def rename_node(req, node_id):
        """自定义节点名称；name 为空串表示恢复为订阅原始名称（移除自定义键）。"""
        body = req.read_json()
        with ctx.store.transaction():
            nodes = ctx.store.load_nodes()
            target = None
            for n in nodes:
                if n.get("id") == node_id:
                    target = n
                    break
            if not target:
                return _err("节点不存在", 404)
            if "name" in body:
                custom = str(body["name"] or "").strip()
                if len(custom) > 64:
                    return _err("节点名称过长（最多 64 字符）")
                if custom:
                    target["custom_name"] = custom
                else:
                    # 空串显式清除自定义名称，恢复订阅原始名称
                    target.pop("custom_name", None)
            ctx.store.save_nodes(nodes)
        return _ok(node={
            "id": target.get("id"),
            "name": target.get("name") or "",
            "custom_name": target.get("custom_name") or "",
            "display_name": target.get("custom_name") or target.get("name") or "",
        })

    @app.route("POST", r"/api/nodes/([^/]+)/test")
    def test_node(req, node_id):
        with ctx.store.transaction():
            nodes = ctx.store.load_nodes()
            node = None
            for n in nodes:
                if n.get("id") == node_id:
                    node = n
                    break
            if not node:
                return _err("节点不存在", 404)
            latency = _tcp_ping(node.get("server"), int(node.get("port") or 0))
            for n in nodes:
                if n.get("id") == node_id:
                    n["latency"] = latency
                    break
            ctx.store.save_nodes(nodes)
        return _ok(latency=latency)

    # ---------------------------------------------------------------- 代理配置（多条目）
    LISTEN_ALLOW = ("0.0.0.0", "127.0.0.1", "::", "::1", "localhost")

    def _proxy_out(p, nodes=None):
        out = {
            "id": p.get("id"),
            "enabled": bool(p.get("enabled")),
            "listen": p.get("listen") or "0.0.0.0",
            "port": int(p.get("port") or 1080),
            "username": p.get("username") or "",
            "has_password": bool(p.get("password")),
            "udp": bool(p.get("udp")),
            "node_id": p.get("node_id") or "",
        }
        if nodes is not None:
            out["node_name"] = next((n.get("name") for n in nodes if n.get("id") == p.get("node_id")), None)
        return out

    def _validate_proxy(proxies, body, exclude_id=None):
        listen = str(body.get("listen") or "0.0.0.0")
        if listen not in LISTEN_ALLOW:
            return None, "监听地址不合法，可选 0.0.0.0 / 127.0.0.1 / :: / ::1"
        port = int(body.get("port") or 0)
        if not util.is_valid_port(port):
            return None, "端口必须在 1-65535 之间"
        for p in proxies:
            if p.get("id") == exclude_id:
                continue
            if int(p.get("port") or 0) == port:
                return None, "端口 %d 已被其他代理条目占用" % port
        return (listen, port), None

    @app.route("GET", r"/api/config/proxies")
    def get_proxies(req):
        settings = ctx.store.load_settings()
        proxies = settings.get("proxies") or []
        nodes = ctx.store.load_nodes()
        return _ok(proxies=[_proxy_out(p, nodes) for p in proxies],
                   active_node_id=settings.get("active_node_id"))

    @app.route("POST", r"/api/config/proxies")
    def add_proxy(req):
        body = req.read_json()
        with ctx.store.transaction():
            settings = ctx.store.load_settings()
            proxies = settings.get("proxies") or []
            v, err = _validate_proxy(proxies, body)
            if err:
                return _err(err)
            listen, port = v
            proxy = {
                "id": "proxy-%s" % util.gen_id(),
                "enabled": bool(body.get("enabled", True)),
                "listen": listen,
                "port": port,
                "username": str(body.get("username") or ""),
                "password": str(body.get("password") or ""),
                "udp": bool(body.get("udp")),
                "node_id": body.get("node_id") or "",
            }
            proxies.append(proxy)
            settings["proxies"] = proxies
            ctx.store.save_settings(settings)
            nodes = ctx.store.load_nodes()
        return _ok(proxy=_proxy_out(proxy, nodes))

    @app.route("PUT", r"/api/config/proxies/([^/]+)")
    def update_proxy(req, pid):
        body = req.read_json()
        with ctx.store.transaction():
            settings = ctx.store.load_settings()
            proxies = settings.get("proxies") or []
            target = None
            for p in proxies:
                if p.get("id") == pid:
                    target = p
                    break
            if not target:
                return _err("代理条目不存在", 404)
            probe = {
                "listen": body.get("listen", target.get("listen") or "0.0.0.0"),
                "port": body.get("port", target.get("port") or 0),
            }
            v, err = _validate_proxy(proxies, probe, exclude_id=pid)
            if err:
                return _err(err)
            listen, port = v
            target["listen"] = listen
            target["port"] = port
            if "enabled" in body:
                target["enabled"] = bool(body["enabled"])
            if "username" in body:
                target["username"] = str(body["username"] or "")
            if "password" in body:
                if body["password"]:
                    target["password"] = str(body["password"])
                elif body.get("username") == "":
                    target["password"] = ""
            if "udp" in body:
                target["udp"] = bool(body["udp"])
            if "node_id" in body:
                target["node_id"] = body["node_id"] or ""
            ctx.store.save_settings(settings)
            nodes = ctx.store.load_nodes()
        return _ok(proxy=_proxy_out(target, nodes))

    @app.route("DELETE", r"/api/config/proxies/([^/]+)")
    def delete_proxy(req, pid):
        with ctx.store.transaction():
            settings = ctx.store.load_settings()
            proxies = settings.get("proxies") or []
            new_list = [p for p in proxies if p.get("id") != pid]
            if len(new_list) == len(proxies):
                return _err("代理条目不存在", 404)
            settings["proxies"] = new_list
            ctx.store.save_settings(settings)
        return _ok(message="已删除")

    def _resolve_active_node(settings, proxies, nodes):
        return resolve_active_node(ctx.store, settings, proxies, nodes, ctx.log)

    @app.route("POST", r"/api/config/proxies/apply")
    def apply_proxies(req):
        with ctx.store.transaction():
            settings = ctx.store.load_settings()
            proxies = settings.get("proxies") or []
            proxy_snapshot = [dict(p) for p in proxies]
            nodes = ctx.store.load_nodes()
            settings_snapshot = dict(settings)
        # 应用阶段在锁外执行（避免阻塞服务端响应并避免长任务持锁）
        node, err = _resolve_active_node(settings_snapshot, proxy_snapshot, nodes)
        if err:
            return _err(err)
        ok, msg = ctx.core.apply(proxy_snapshot, node, nodes)
        return _ok(success=ok, message=msg)

    # 兼容旧版单条 SOCKS 接口（不再返回明文密码）
    @app.route("GET", r"/api/config/socks")
    def get_socks(req):
        settings = ctx.store.load_settings()
        proxies = settings.get("proxies") or []
        first = proxies[0] if proxies else {}
        return _ok(socks={
            "enabled": bool(first.get("enabled")),
            "listen": first.get("listen") or "0.0.0.0",
            "port": int(first.get("port") or 1080),
            "username": first.get("username") or "",
            "has_password": bool(first.get("password")),
            "udp": bool(first.get("udp")),
        }, active_node_id=settings.get("active_node_id"))

    @app.route("PUT", r"/api/config/socks")
    def put_socks(req):
        body = req.read_json()
        with ctx.store.transaction():
            settings = ctx.store.load_settings()
            proxies = settings.get("proxies") or []
            if not proxies:
                proxies = [{
                    "id": "proxy-%s" % util.gen_id(),
                    "enabled": False,
                    "listen": "0.0.0.0",
                    "port": 1080,
                    "username": "",
                    "password": "",
                    "udp": False,
                }]
                settings["proxies"] = proxies
            target = proxies[0]
            if "enabled" in body:
                target["enabled"] = bool(body["enabled"])
            if "listen" in body:
                v, err = _validate_proxy(proxies, {"listen": body["listen"], "port": target.get("port")}, exclude_id=target.get("id"))
                if err:
                    return _err(err)
                target["listen"] = v[0]
            if "port" in body:
                v, err = _validate_proxy(proxies, {"listen": target.get("listen"), "port": body["port"]}, exclude_id=target.get("id"))
                if err:
                    return _err(err)
                target["port"] = v[1]
            if "username" in body:
                target["username"] = str(body["username"] or "")
            if "password" in body:
                target["password"] = str(body["password"] or "")
            if "udp" in body:
                target["udp"] = bool(body["udp"])
            if "node_id" in body:
                settings["active_node_id"] = body["node_id"] or None
            ctx.store.save_settings(settings)
        return _ok(socks=_proxy_out(target))

    @app.route("POST", r"/api/config/socks/apply")
    def apply_socks(req):
        with ctx.store.transaction():
            settings = ctx.store.load_settings()
            proxies = settings.get("proxies") or []
            proxy_snapshot = [dict(p) for p in proxies]
            nodes = ctx.store.load_nodes()
            settings_snapshot = dict(settings)
        node, err = _resolve_active_node(settings_snapshot, proxy_snapshot, nodes)
        if err:
            return _err(err)
        ok, msg = ctx.core.apply(proxy_snapshot, node, nodes)
        return _ok(success=ok, message=msg)

    # ---------------------------------------------------------------- 核心
    @app.route("GET", r"/api/core/status")
    def core_status(req):
        return _ok(**ctx.core.status())

    @app.route("POST", r"/api/core/start")
    def core_start(req):
        ok, msg = ctx.core.start()
        return _ok(success=ok, message=msg)

    @app.route("POST", r"/api/core/stop")
    def core_stop(req):
        ctx.core.stop()
        return _ok(message="已停止")

    @app.route("POST", r"/api/core/restart")
    def core_restart(req):
        ok, msg = ctx.core.restart()
        return _ok(success=ok, message=msg)

    # ---------------------------------------------------------------- 设置
    @app.route("GET", r"/api/settings")
    def get_settings(req):
        settings = ctx.store.load_settings()
        configured = settings.get("core", {}).get("binary") or ctx.core.core_binary
        # 不暴露绝对路径之外的敏感信息
        return _ok(
            core_binary=configured,
            core_binary_allowed=is_binary_path_allowed(configured, ctx.core._binary_whitelist),
            data_dir=ctx.store.data_dir,
        )

    @app.route("PUT", r"/api/settings")
    def put_settings(req):
        body = req.read_json()
        if "core_binary" in body:
            new_path = str(body["core_binary"] or "").strip()
            if new_path and not is_binary_path_allowed(new_path, ctx.core._binary_whitelist):
                return _err("核心路径不在允许目录内，已拒绝（防止任意命令执行）", 403)
            with ctx.store.transaction():
                settings = ctx.store.load_settings()
                core = settings.get("core") or {}
                core["binary"] = new_path
                settings["core"] = core
                ctx.store.save_settings(settings)
            ctx.core.set_binary(new_path)
        return _ok()

    # ---------------------------------------------------------------- 日志
    @app.route("GET", r"/api/logs")
    def get_logs(req):
        source = req.get_param("source", "core")
        try:
            lines = int(req.get_param("lines", "200") or 200)
        except ValueError:
            lines = 200
        lines = max(1, min(lines, 5000))
        if source == "app":
            path = ctx.app_log_path
        else:
            path = ctx.core_log_path
        return _ok(lines=tail_log(path, lines), source=source)


def _tcp_ping(host, port, timeout=3.0):
    """简单的 TCP 连通性测试，返回毫秒延迟；失败返回 None。"""
    if not host or not port:
        return None
    import time
    try:
        start = time.monotonic()
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
        elapsed = (time.monotonic() - start) * 1000
        return int(max(elapsed, 1))
    except OSError:
        return None