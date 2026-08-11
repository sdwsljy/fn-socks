# -*- coding: utf-8 -*-
"""持久化存储：订阅、节点、设置分别存放在独立的 JSON 文件（原子写入 + 全局锁）。"""
import os
import threading

from . import util


class Store(object):
    def __init__(self, data_dir):
        self.data_dir = util.ensure_dir(data_dir)
        self.subs_file = os.path.join(self.data_dir, "subscriptions.json")
        self.nodes_file = os.path.join(self.data_dir, "nodes.json")
        self.settings_file = os.path.join(self.data_dir, "settings.json")
        self.log_dir = os.path.join(self.data_dir, "logs")
        util.ensure_dir(self.log_dir)
        # 单一互斥锁：ThreadingHTTPServer 每请求一线程，
        # 多请求并发读写 settings/nodes/subs 会相互覆盖增量，必须串行化。
        self._lock = threading.RLock()

    def transaction(self):
        """临界区上下文：在 with 内的 load+modify+save 组合可原子化。"""
        return self._lock

    # ---------------------------------------------------------- subs
    def load_subs(self):
        subs = util.read_json(self.subs_file, [])
        if not isinstance(subs, list):
            subs = []
        return subs

    def save_subs(self, subs):
        with self._lock:
            util.write_json(self.subs_file, subs)

    def update_subs(self, fn):
        """读改写原子操作：fn(subs_list)->new_subs_list。"""
        with self._lock:
            subs = self.load_subs()
            subs = fn(subs) or subs
            util.write_json(self.subs_file, subs)
            return subs

    # ---------------------------------------------------------- nodes
    def load_nodes(self):
        nodes = util.read_json(self.nodes_file, [])
        if not isinstance(nodes, list):
            nodes = []
        return nodes

    def save_nodes(self, nodes):
        with self._lock:
            util.write_json(self.nodes_file, nodes)

    def update_nodes(self, fn):
        with self._lock:
            nodes = self.load_nodes()
            nodes = fn(nodes) or nodes
            util.write_json(self.nodes_file, nodes)
            return nodes

    # ---------------------------------------------------------- settings
    def load_settings(self):
        s = util.read_json(self.settings_file, {})
        if not isinstance(s, dict):
            s = {}
        if "proxies" not in s and s.get("socks"):
            old = s.get("socks") or {}
            s["proxies"] = [{
                "id": "proxy-1",
                "enabled": bool(old.get("enabled")),
                "listen": old.get("listen") or "0.0.0.0",
                "port": int(old.get("port") or 1080),
                "username": old.get("username") or "",
                "password": old.get("password") or "",
                "udp": bool(old.get("udp")),
            }]
            # 迁移完成后移除旧字段
            s.pop("socks", None)
            try:
                util.write_json(self.settings_file, s)
            except Exception:
                pass
        if "proxies" not in s:
            s["proxies"] = []
        return s

    def save_settings(self, settings):
        with self._lock:
            util.write_json(self.settings_file, settings)

    def update_settings(self, fn):
        with self._lock:
            s = self.load_settings()
            s = fn(s) or s
            util.write_json(self.settings_file, s)
            return s