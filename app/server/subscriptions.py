# -*- coding: utf-8 -*-
"""订阅管理：增删改查、定时更新、抓取与解析、节点替换。"""
import ipaddress
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import parsers, util
from .logger import get_logger

DEFAULT_UA = "v2rayN/9.99"
MAX_CONTENT = 8 * 1024 * 1024  # 8MB 上限
MAX_REDIRECTS = 3  # 最大重定向次数
AUTO_UPDATE_TICK = 60  # 自动更新扫描间隔（秒）


def _is_safe_target(url):
    """目标 URL 安全校验：scheme 仅限 http/https，目的 IP 不能是私网/回环/链路本地/保留等。

    在 e2e 测试等本地场景下，可设置环境变量 `FN_SOCKS_ALLOW_LOCAL_SUBSCRIPTION=1`
    临时放开本地地址过滤（生产环境禁止开启），否则云端元数据等内网端点会被攻击者用订阅抓取读取。
    """
    try:
        u = urllib.parse.urlsplit(url)
    except Exception:
        return False
    if (u.scheme or "").lower() not in ("http", "https"):
        return False
    host = u.hostname or ""
    if not host:
        return False
    allow_local = os.environ.get("FN_SOCKS_ALLOW_LOCAL_SUBSCRIPTION", "").lower() in ("1", "true", "yes")
    if allow_local:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, OSError):
        return False
    if not infos:
        return False
    for family, _, _, _, sockaddr in infos:
        ip = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip)
        except (ValueError, TypeError):
            return False
        # 拦截内网/回环/链路本地/保留/多播/未指定地址，同时拦截 IPv6 ULA/默认 NAT64
        if (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
                or ip_obj.is_reserved or ip_obj.is_multicast or ip_obj.is_unspecified):
            return False
        # is_private 对 0.0.0.0/8 / 100.64/10 等的限制因 Python 版本而异，额外显式拦截
        if ip == "0.0.0.0" or ip == "::":
            return False
    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """自定义重定向处理器：拦截并逐跳校验目的地址，限制跳数。"""

    max_repeats = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_safe_target(newurl):
            raise urllib.error.URLError("重定向目标不安全: %s" % _mask_url(newurl))
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


def _mask_url(url):
    """日志脱敏：保留 scheme+host，去除路径/查询（机场 URL 中常含 token）。"""
    try:
        u = urllib.parse.urlsplit(url)
        netloc = u.hostname or ""
        if u.port:
            netloc = "%s:%d" % (netloc, u.port)
        return "%s://%s/***" % (u.scheme, netloc)
    except Exception:
        return "***"


class SubscriptionManager(object):
    def __init__(self, store, logger=None):
        self.store = store
        self.log = logger or get_logger(tag="sub")
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener(_SafeRedirectHandler)
        self._auto_thread = None
        self._stop_evt = threading.Event()

    # ---------------------------------------------------------- 自动更新调度
    def start_auto_updater(self):
        """启动后台扫描线程：周期性检查 interval_min 并触发更新。"""
        if self._auto_thread is not None:
            return
        def _loop():
            while not self._stop_evt.is_set():
                try:
                    subs = self.store.load_subs()
                    now = util.now_ts()
                    for s in subs:
                        interval = int(s.get("interval_min") or 0)
                        if interval <= 0:
                            continue
                        last = int(s.get("last_update") or 0)
                        if last and (now - last) < interval * 60:
                            continue
                        try:
                            self.log.info("自动更新订阅: %s" % s.get("remark"))
                            self.update_sub(s["id"])
                        except Exception as e:
                            self.log.error("自动更新订阅[%s]失败: %s" % (s.get("remark"), e))
                except Exception as e:
                    self.log.error("自动更新扫描异常: %s" % e)
                self._stop_evt.wait(AUTO_UPDATE_TICK)
        self._auto_thread = threading.Thread(target=_loop, name="sub-auto-updater", daemon=True)
        self._auto_thread.start()
        self.log.info("订阅自动更新调度已启动（间隔 %ds）" % AUTO_UPDATE_TICK)

    def stop_auto_updater(self):
        if self._auto_thread is None:
            return
        self._stop_evt.set()
        try:
            self._auto_thread.join(timeout=2)
        except Exception:
            pass
        self._auto_thread = None

    # ---------------------------------------------------------- 基础 CRUD
    def list_subs(self):
        return self.store.load_subs()

    def get_sub(self, sub_id):
        for s in self.store.load_subs():
            if s.get("id") == sub_id:
                return s
        return None

    @staticmethod
    def _validate_url(url):
        url = (url or "").strip()
        if not url:
            raise ValueError("订阅链接不能为空")
        try:
            u = urllib.parse.urlsplit(url)
        except Exception:
            raise ValueError("订阅链接格式无效")
        if (u.scheme or "").lower() not in ("http", "https"):
            raise ValueError("订阅链接必须以 http:// 或 https:// 开头")
        if not (u.hostname or ""):
            raise ValueError("订阅链接缺少主机名")
        return url

    def add_sub(self, url, remark="", user_agent="", interval_min=0):
        url = self._validate_url(url)
        subs = self.store.load_subs()
        for s in subs:
            if s.get("url") == url:
                raise ValueError("该订阅链接已存在")
        sub = {
            "id": util.new_id(),
            "url": url,
            "remark": remark.strip() or self._remark_from_url(url),
            "user_agent": user_agent.strip() or DEFAULT_UA,
            "interval_min": int(interval_min or 0),
            "last_update": 0,
            "node_count": 0,
            "format": "",
            "info": {},
            "error": None,
        }
        subs.append(sub)
        self.store.save_subs(subs)
        # 日志脱敏：URL 中常含机场 token
        self.log.info("添加订阅: %s (%s)" % (sub["remark"], _mask_url(url)))
        return sub

    def update_sub_meta(self, sub_id, **fields):
        with self.store.transaction():
            subs = self.store.load_subs()
            for s in subs:
                if s.get("id") == sub_id:
                    for k, v in fields.items():
                        s[k] = v
                    self.store.save_subs(subs)
                    return s
        return None

    def delete_sub(self, sub_id):
        with self.store.transaction():
            subs = self.store.load_subs()
            subs = [s for s in subs if s.get("id") != sub_id]
            self.store.save_subs(subs)
            nodes = self.store.load_nodes()
            removed_nodes = [n for n in nodes if n.get("sub_id") == sub_id]
            nodes = [n for n in nodes if n.get("sub_id") != sub_id]
            self.store.save_nodes(nodes)
            # 若当前选中节点属于该订阅，清空 active_node_id
            settings = self.store.load_settings()
            if removed_nodes and settings.get("active_node_id") in [n.get("id") for n in removed_nodes]:
                settings["active_node_id"] = None
                self.store.save_settings(settings)
            self.log.info("删除订阅 %s 及其 %d 个节点" % (sub_id, len(removed_nodes)))
            return True

    @staticmethod
    def _remark_from_url(url):
        m = re.search(r"https?://([^/]+)", url)
        return m.group(1) if m else url

    # ---------------------------------------------------------- 抓取与解析
    def fetch(self, sub):
        url = sub.get("url", "")
        if not _is_safe_target(url):
            raise ValueError("订阅地址不安全（被拒绝策略）: %s" % _mask_url(url))
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": sub.get("user_agent") or DEFAULT_UA,
                "Accept-Encoding": "identity",
            },
        )
        try:
            with self._opener.open(req, timeout=30) as resp:
                # 再次校验最终 URL（重定向后的最终目的地）
                if not _is_safe_target(resp.geturl()):
                    raise ValueError("订阅最终地址不安全: %s" % _mask_url(resp.geturl()))
                raw = resp.read(MAX_CONTENT + 1)
                if len(raw) > MAX_CONTENT:
                    raise ValueError("订阅内容超过 8MB 上限")
                headers = dict(resp.headers.items())
                try:
                    body = raw.decode("utf-8")
                except UnicodeDecodeError:
                    body = raw.decode("gbk", errors="replace")
                return body, headers
        except urllib.error.HTTPError as e:
            raise ValueError("HTTP %d: %s" % (e.code, e.reason or "下载失败"))
        except urllib.error.URLError as e:
            raise ValueError("网络错误: %s" % (e.reason or e))
        except (OSError, ValueError) as e:
            raise ValueError(str(e))

    @staticmethod
    def parse_userinfo(headers):
        """解析 subscription-userinfo 等响应头。"""
        info = {}
        raw = headers.get("Subscription-Userinfo") or headers.get("subscription-userinfo")
        if raw:
            for kv in raw.split(";"):
                kv = kv.strip()
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    info[k.strip()] = v.strip()
        title = headers.get("Profile-Title") or headers.get("profile-title")
        if title:
            info["title"] = title
        return info

    # ---------------------------------------------------------- 更新
    def update_sub(self, sub_id):
        with self._lock:
            sub = self.get_sub(sub_id)
            if not sub:
                raise ValueError("订阅不存在")
            body, headers = self.fetch(sub)
            nodes, fmt, parsed, failed = parsers.parse_subscription_text(body)
            if not nodes and fmt != "empty":
                raise ValueError(
                    "未能从订阅中解析出任何节点（格式: %s, 失败 %d 条）" % (fmt, failed)
                )
            info = self.parse_userinfo(headers)
            now = util.now_ts()
            # 在 store 事务内完成节点替换 + 元数据回写
            with self.store.transaction():
                all_nodes = self.store.load_nodes()
                kept = [n for n in all_nodes if n.get("sub_id") != sub_id]
                # 旧节点中带自定义名称的，按 (type, server, port) 迁移到新节点
                custom_map = {}
                for old in all_nodes:
                    if old.get("sub_id") == sub_id and old.get("custom_name"):
                        key = (old.get("type"), old.get("server"), int(old.get("port") or 0))
                        custom_map[key] = old["custom_name"]
                for n in nodes:
                    n["id"] = util.new_id()
                    n["sub_id"] = sub_id
                    n["group"] = sub.get("remark") or sub_id
                    n["created_at"] = now
                    key = (n.get("type"), n.get("server"), int(n.get("port") or 0))
                    if key in custom_map:
                        n["custom_name"] = custom_map[key]
                kept.extend(nodes)
                self.store.save_nodes(kept)
                # 若当前无选中节点且本次更新产生了节点，自动选择第一个
                settings = self.store.load_settings()
                if not settings.get("active_node_id") and nodes:
                    settings["active_node_id"] = nodes[0]["id"]
                    self.store.save_settings(settings)
                    self.log.info("自动选择节点: %s" % (
                        nodes[0].get("custom_name") or nodes[0].get("name") or nodes[0].get("id")))
                # 元数据回写（同事务）
                subs = self.store.load_subs()
                for s in subs:
                    if s.get("id") == sub_id:
                        s["last_update"] = now
                        s["node_count"] = len(nodes)
                        s["format"] = fmt
                        s["info"] = info
                        s["error"] = None
                        break
                self.store.save_subs(subs)
            self.log.info(
                "更新订阅[%s] 完成: %d 个节点 (格式=%s, 失败=%d)"
                % (sub.get("remark"), len(nodes), fmt, failed)
            )
            return {"nodes": len(nodes), "format": fmt, "failed": failed, "info": info}

    def update_all(self):
        subs = self.store.load_subs()
        results = []
        for s in subs:
            try:
                r = self.update_sub(s["id"])
                results.append({"id": s["id"], "remark": s.get("remark"), "ok": True, **r})
            except Exception as e:
                self.log.error("更新订阅[%s]失败: %s" % (s.get("remark"), e))
                self.update_sub_meta(s["id"], error=str(e))
                results.append({"id": s["id"], "remark": s.get("remark"), "ok": False, "error": str(e)})
        return results

    # ---------------------------------------------------------- 手动导入
    def import_links(self, text, group="手动导入"):
        text = text or ""
        if not text.strip():
            raise ValueError("内容为空")
        nodes = parsers.parse_links_text(text)
        if not nodes:
            raise ValueError("未识别出任何有效节点链接")
        with self.store.transaction():
            all_nodes = self.store.load_nodes()
            now = util.now_ts()
            added = 0
            for n in nodes:
                n["id"] = util.new_id()
                n["sub_id"] = "manual"
                n["group"] = group.strip() or "手动导入"
                n["created_at"] = now
                all_nodes.append(n)
                added += 1
            self.store.save_nodes(all_nodes)
            # 若当前无选中节点且本次导入产生了节点，自动选择第一个
            settings = self.store.load_settings()
            if not settings.get("active_node_id") and nodes:
                settings["active_node_id"] = nodes[0]["id"]
                self.store.save_settings(settings)
                self.log.info("自动选择节点: %s" % (
                    nodes[0].get("custom_name") or nodes[0].get("name") or nodes[0].get("id")))
        self.log.info("手动导入 %d 个节点（组: %s）" % (added, group))
        return added

    def delete_node(self, node_id):
        with self.store.transaction():
            nodes = self.store.load_nodes()
            before = len(nodes)
            nodes = [n for n in nodes if n.get("id") != node_id]
            self.store.save_nodes(nodes)
            settings = self.store.load_settings()
            if settings.get("active_node_id") == node_id:
                settings["active_node_id"] = None
                self.store.save_settings(settings)
        return before != len(nodes)