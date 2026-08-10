# -*- coding: utf-8 -*-
"""持久化存储：订阅、节点、设置分别存放在独立的 JSON 文件（原子写入）。"""
import os

from . import util


class Store(object):
    def __init__(self, data_dir):
        self.data_dir = util.ensure_dir(data_dir)
        self.subs_file = os.path.join(self.data_dir, "subscriptions.json")
        self.nodes_file = os.path.join(self.data_dir, "nodes.json")
        self.settings_file = os.path.join(self.data_dir, "settings.json")
        self.log_dir = os.path.join(self.data_dir, "logs")
        util.ensure_dir(self.log_dir)

    def load_subs(self):
        subs = util.read_json(self.subs_file, [])
        if not isinstance(subs, list):
            subs = []
        return subs

    def save_subs(self, subs):
        util.write_json(self.subs_file, subs)

    def load_nodes(self):
        nodes = util.read_json(self.nodes_file, [])
        if not isinstance(nodes, list):
            nodes = []
        return nodes

    def save_nodes(self, nodes):
        util.write_json(self.nodes_file, nodes)

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
        if "proxies" not in s:
            s["proxies"] = []
        return s

    def save_settings(self, settings):
        util.write_json(self.settings_file, settings)
