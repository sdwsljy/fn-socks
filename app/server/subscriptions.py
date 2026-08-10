# -*- coding: utf-8 -*-
"""订阅管理：增删改查、定时更新、抓取与解析、节点替换。"""
import os
import re
import threading
import urllib.error
import urllib.request

from . import parsers, util
from .logger import get_logger

DEFAULT_UA = "v2rayN/9.99"
MAX_CONTENT = 8 * 1024 * 1024  # 8MB 上限


class SubscriptionManager(object):
    def __init__(self, store, logger=None):
        self.store = store
        self.log = logger or get_logger(tag="sub")
        self._lock = threading.Lock()

    # ---------------------------------------------------------- 基础 CRUD
    def list_subs(self):
        return self.store.load_subs()

    def get_sub(self, sub_id):
        for s in self.store.load_subs():
            if s.get("id") == sub_id:
                return s
        return None

    def add_sub(self, url, remark="", user_agent="", interval_min=0):
        url = (url or "").strip()
        if not url:
            raise ValueError("订阅链接不能为空")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("订阅链接必须以 http:// 或 https:// 开头")
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
        self.log.info("添加订阅: %s (%s)" % (sub["remark"], url))
        return sub

    def update_sub_meta(self, sub_id, **fields):
        subs = self.store.load_subs()
        for s in subs:
            if s.get("id") == sub_id:
                for k, v in fields.items():
                    s[k] = v
                self.store.save_subs(subs)
                return s
        return None

    def delete_sub(self, sub_id):
        subs = self.store.load_subs()
        subs = [s for s in subs if s.get("id") != sub_id]
        self.store.save_subs(subs)
        # 同时删除该订阅下的节点
        nodes = self.store.load_nodes()
        nodes = [n for n in nodes if n.get("sub_id") != sub_id]
        self.store.save_nodes(nodes)
        self.log.info("删除订阅 %s 及其 %d 个节点" % (sub_id, 0))
        return True

    @staticmethod
    def _remark_from_url(url):
        m = re.search(r"https?://([^/]+)", url)
        return m.group(1) if m else url

    # ---------------------------------------------------------- 抓取与解析
    def fetch(self, sub):
        req = urllib.request.Request(
            sub.get("url", ""),
            headers={
                "User-Agent": sub.get("user_agent") or DEFAULT_UA,
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
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
            all_nodes = self.store.load_nodes()
            kept = [n for n in all_nodes if n.get("sub_id") != sub_id]
            now = util.now_ts()
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
                self.log.info("自动选择节点: %s" % (nodes[0].get("name") or nodes[0].get("id")))
            meta = {
                "last_update": now,
                "node_count": len(nodes),
                "format": fmt,
                "info": info,
                "error": None,
            }
            self.update_sub_meta(sub_id, **meta)
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
            self.log.info("自动选择节点: %s" % (nodes[0].get("name") or nodes[0].get("id")))
        self.log.info("手动导入 %d 个节点（组: %s）" % (added, group))
        return added

    def delete_node(self, node_id):
        nodes = self.store.load_nodes()
        before = len(nodes)
        nodes = [n for n in nodes if n.get("id") != node_id]
        self.store.save_nodes(nodes)
        settings = self.store.load_settings()
        if settings.get("active_node_id") == node_id:
            settings["active_node_id"] = None
            self.store.save_settings(settings)
        return before != len(nodes)
