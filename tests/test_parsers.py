# -*- coding: utf-8 -*-
"""解析器与配置生成单元测试。

运行: python -m unittest tests.test_parsers -v
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.server import parsers
from app.server.core import config_gen
from app.server.parsers import helpers


def node_data(node, key):
    return (node.get("data") or {}).get(key)


class TestBase64(unittest.TestCase):
    def test_urlsafe_without_pad(self):
        self.assertEqual(helpers.b64decode_str("YWVzLTI1Ni1nY206cHdk"), "aes-256-gcm:pwd")

    def test_invalid_returns_none(self):
        self.assertIsNone(helpers.b64decode_any("!!!"))


class TestSS(unittest.TestCase):
    def test_base64_userinfo(self):
        n = parsers.parse_link("ss://YWVzLTI1Ni1nY206cHdk@1.2.3.4:8388#HK%201")
        self.assertEqual(n["type"], "ss")
        self.assertEqual(n["server"], "1.2.3.4")
        self.assertEqual(n["port"], 8388)
        self.assertEqual(n["name"], "HK 1")
        self.assertEqual(n["data"]["method"], "aes-256-gcm")
        self.assertEqual(n["data"]["password"], "pwd")

    def test_plain_userinfo(self):
        n = parsers.parse_link("ss://aes-256-gcm:pass@example.com:443#test")
        self.assertEqual(n["data"]["method"], "aes-256-gcm")
        self.assertEqual(n["data"]["password"], "pass")

    def test_whole_payload_base64(self):
        link = "ss://YWVzLTI1Ni1nY206cHdkQDEuMi4zLjQ6ODM4OA"
        n = parsers.parse_link(link)
        self.assertIsNotNone(n)
        self.assertEqual(n["server"], "1.2.3.4")
        self.assertEqual(n["port"], 8388)

    def test_plugin(self):
        n = parsers.parse_link(
            "ss://YWVzLTI1Ni1nY206cHdk@1.2.3.4:443?plugin=v2ray-plugin%3Btls%3Bhost%3Dabc.com#x"
        )
        self.assertIn("plugin", n["data"])

    def test_ipv6(self):
        n = parsers.parse_link("ss://YWVzLTI1Ni1nY206cHdk@[2001:db8::1]:8388#v6")
        self.assertEqual(n["server"], "2001:db8::1")
        self.assertEqual(n["port"], 8388)


class TestSSR(unittest.TestCase):
    def test_ssr(self):
        payload = helpers.b64encode_str(
            "1.2.3.4:443:origin:aes-256-cfb:plain:" +
            helpers.b64encode_str("ssrpass", urlsafe=True) +
            "/?remarks=" + helpers.b64encode_str("SSR节点", urlsafe=True),
            urlsafe=True,
        )
        n = parsers.parse_link("ssr://" + payload)
        self.assertEqual(n["type"], "ssr")
        self.assertEqual(n["server"], "1.2.3.4")
        self.assertEqual(n["port"], 443)
        self.assertEqual(n["data"]["password"], "ssrpass")
        self.assertEqual(n["data"]["protocol"], "origin")
        self.assertEqual(n["data"]["obfs"], "plain")


class TestVMess(unittest.TestCase):
    def test_json_base64(self):
        vm = {
            "v": "2", "ps": "VM测试", "add": "vm.example.com", "port": "443",
            "id": "uuid-1234", "aid": "0", "scy": "auto", "net": "ws",
            "type": "none", "host": "cdn.example.com", "path": "/ws", "tls": "tls",
            "sni": "cdn.example.com", "fp": "chrome",
        }
        link = "vmess://" + helpers.b64encode_str(json.dumps(vm))
        n = parsers.parse_link(link)
        self.assertEqual(n["type"], "vmess")
        self.assertEqual(n["name"], "VM测试")
        self.assertEqual(n["server"], "vm.example.com")
        self.assertEqual(n["data"]["uuid"], "uuid-1234")
        self.assertEqual(n["data"]["network"], "ws")
        self.assertEqual(n["data"]["path"], "/ws")
        self.assertEqual(n["data"]["tls"], True)
        self.assertEqual(n["data"]["sni"], "cdn.example.com")

    def test_new_format(self):
        link = "vmess://uuid-999@vm2.example.com:8443?type=grpc&security=tls&serviceName=svc&sni=vm2.example.com#GRPC"
        n = parsers.parse_link(link)
        self.assertEqual(n["type"], "vmess")
        self.assertEqual(n["data"]["network"], "grpc")
        self.assertEqual(n["data"]["service_name"], "svc")
        self.assertEqual(n["data"]["tls"], True)


class TestVLESS(unittest.TestCase):
    def test_reality(self):
        link = ("vless://uuid-reality@re.example.com:443?type=tcp&security=reality"
                "&pbk=pubkey&sid=abcd&fp=chrome&sni=re.example.com&flow=xtls-rprx-vision#Reality")
        n = parsers.parse_link(link)
        self.assertEqual(n["type"], "vless")
        self.assertEqual(n["data"]["reality"], True)
        self.assertEqual(n["data"]["pbk"], "pubkey")
        self.assertEqual(n["data"]["sid"], "abcd")
        self.assertEqual(n["data"]["flow"], "xtls-rprx-vision")

    def test_ws_tls(self):
        link = ("vless://uuid-ws@w.example.com:443?type=ws&security=tls"
                "&path=%2Fabc&host=w.example.com&sni=w.example.com&fp=firefox#WS")
        n = parsers.parse_link(link)
        self.assertEqual(n["data"]["network"], "ws")
        self.assertEqual(n["data"]["path"], "/abc")
        self.assertEqual(n["data"]["host"], "w.example.com")
        self.assertEqual(n["data"]["tls"], True)


class TestTrojan(unittest.TestCase):
    def test_basic(self):
        link = "trojan://pass123@tr.example.com:443?sni=tr.example.com&type=ws&path=%2Ftr#TR"
        n = parsers.parse_link(link)
        self.assertEqual(n["type"], "trojan")
        self.assertEqual(n["data"]["password"], "pass123")
        self.assertEqual(n["data"]["network"], "ws")
        self.assertEqual(n["data"]["sni"], "tr.example.com")


class TestHysteria2(unittest.TestCase):
    def test_basic(self):
        link = "hysteria2://hy2pass@hy.example.com:8443?insecure=1&sni=hy.example.com#HY2"
        n = parsers.parse_link(link)
        self.assertEqual(n["type"], "hysteria2")
        self.assertEqual(n["data"]["password"], "hy2pass")
        self.assertEqual(n["data"]["insecure"], True)
        self.assertEqual(n["data"]["sni"], "hy.example.com")


class TestTuic(unittest.TestCase):
    def test_basic(self):
        link = "tuic://uuid-t:tuicpass@tu.example.com:9443?congestion_control=bbr&alpn=h3&sni=tu.example.com#TUIC"
        n = parsers.parse_link(link)
        self.assertEqual(n["type"], "tuic")
        self.assertEqual(n["data"]["uuid"], "uuid-t")
        self.assertEqual(n["data"]["password"], "tuicpass")
        self.assertEqual(n["data"]["congestion_control"], "bbr")
        self.assertEqual(n["data"]["alpn"], ["h3"])


class TestSocks(unittest.TestCase):
    def test_basic(self):
        n = parsers.parse_link("socks5://user:pass@s.example.com:1080#SOCKS")
        self.assertEqual(n["type"], "socks")
        self.assertEqual(n["data"]["username"], "user")
        self.assertEqual(n["data"]["password"], "pass")


class TestClash(unittest.TestCase):
    def test_clash_yaml(self):
        text = """
port: 7890
socks-port: 7891
proxies:
  - name: "HK 节点"
    type: ss
    server: 1.2.3.4
    port: 8388
    cipher: aes-256-gcm
    password: clashpass
  - name: WS节点
    type: vmess
    server: vm.example.com
    port: 443
    uuid: uuid-clash
    alterId: 0
    cipher: auto
    network: ws
    ws-opts:
      path: /clash
      headers:
        Host: cdn.example.com
    tls: true
    servername: cdn.example.com
  - name: TR
    type: trojan
    server: tr.example.com
    port: 443
    password: trojanpass
    sni: tr.example.com
  - name: HY
    type: hysteria2
    server: hy.example.com
    port: 8443
    password: hy2
    sni: hy.example.com
"""
        nodes = parsers.clash.parse_clash(text)
        self.assertEqual(len(nodes), 4)
        ss = nodes[0]
        self.assertEqual(ss["name"], "HK 节点")
        self.assertEqual(ss["data"]["method"], "aes-256-gcm")
        vm = nodes[1]
        self.assertEqual(vm["data"]["network"], "ws")
        self.assertEqual(vm["data"]["path"], "/clash")
        self.assertEqual(vm["data"]["host"], "cdn.example.com")
        self.assertEqual(vm["data"]["tls"], True)
        hy = nodes[3]
        self.assertEqual(hy["data"]["sni"], "hy.example.com")

    def test_flow_style_list(self):
        text = """
proxies:
  - name: a
    type: ss
    server: 1.2.3.4
    port: 8388
    cipher: aes-128-gcm
    password: x
    alpn: [h2, http/1.1]
"""
        nodes = parsers.clash.parse_clash(text)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["server"], "1.2.3.4")


class TestSingBoxJSON(unittest.TestCase):
    def test_outbounds_array(self):
        text = json.dumps([
            {"type": "vless", "tag": "SB-VLESS", "server": "sb.example.com",
             "server_port": 443, "uuid": "uuid-sb", "flow": "xtls-rprx-vision",
             "tls": {"enabled": True, "server_name": "sb.example.com", "reality": {"enabled": True}}},
            {"type": "shadowsocks", "tag": "SB-SS", "server": "1.2.3.4",
             "server_port": 8388, "method": "aes-256-gcm", "password": "sbpass"},
        ])
        nodes = parsers.singbox.parse_singbox(text)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["type"], "vless")
        self.assertEqual(nodes[1]["type"], "ss")
        self.assertEqual(nodes[1]["data"]["outbound"]["method"], "aes-256-gcm")


class TestSSD(unittest.TestCase):
    def test_ssd(self):
        doc = {
            "airport": "TestAir", "port": 8388, "encryption": "aes-256-gcm",
            "password": "ssdpass",
            "servers": [{"server": "s1.example.com", "remarks": "S1"}],
        }
        nodes = parsers.ssd.parse_ssd(helpers.b64encode_str(json.dumps(doc)))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["server"], "s1.example.com")
        self.assertEqual(nodes[0]["data"]["method"], "aes-256-gcm")


class TestSubscriptionText(unittest.TestCase):
    def test_base64_subscription(self):
        links = [
            "ss://YWVzLTI1Ni1nY206cHdk@1.2.3.4:8388#A",
            "trojan://pass@tr.example.com:443#B",
        ]
        body = helpers.b64encode_str("\n".join(links))
        nodes, fmt, ok, failed = parsers.parse_subscription_text(body)
        self.assertEqual(fmt, "uri")
        self.assertEqual(len(nodes), 2)

    def test_plain_links(self):
        body = "ss://aes-256-gcm:pass@1.2.3.4:8388#C\nvmess://uuid@v.example.com:443?type=ws#D\n垃圾行"
        nodes, fmt, ok, failed = parsers.parse_subscription_text(body)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(failed, 1)

    def test_empty(self):
        nodes, fmt, ok, failed = parsers.parse_subscription_text("")
        self.assertEqual(fmt, "empty")


class TestConfigGen(unittest.TestCase):
    def _mk(self, ptype, server="1.2.3.4", port=8388, **data):
        return {"name": "n", "type": ptype, "server": server, "port": port, "data": data}

    def test_socks_inbound_noauth(self):
        cfg = config_gen.build_config(
            {"enabled": True, "listen": "0.0.0.0", "port": 1080, "username": "", "password": ""},
            None,
        )
        inbound = cfg["inbounds"][0]
        self.assertEqual(inbound["type"], "mixed", "同一端口应同时提供 SOCKS5 与 HTTP 代理")
        self.assertEqual(inbound["listen_port"], 1080)
        self.assertNotIn("users", inbound)
        self.assertEqual(cfg["route"]["final"], "direct")

    def test_multi_proxies(self):
        cfg = config_gen.build_config([
            {"enabled": True, "listen": "0.0.0.0", "port": 7890, "username": "", "password": ""},
            {"enabled": True, "listen": "127.0.0.1", "port": 1080, "username": "u", "password": "p"},
            {"enabled": False, "listen": "0.0.0.0", "port": 9999, "username": "", "password": ""},
        ], None)
        self.assertEqual(len(cfg["inbounds"]), 2, "仅启用的条目生成入站")
        p0, p1 = cfg["inbounds"]
        self.assertEqual(p0["listen_port"], 7890)
        self.assertEqual(p0["tag"], "mixed-in-0")
        self.assertEqual(p1["listen_port"], 1080)
        self.assertEqual(p1["users"], [{"username": "u", "password": "p"}])
        cfg2 = config_gen.build_config(
            {"enabled": True, "listen": "0.0.0.0", "port": 1080, "username": "", "password": ""}, None)
        self.assertEqual(len(cfg2["inbounds"]), 1)

    def test_proxy_per_node_route(self):
        node_a = {"id": "n-a", "name": "节点A", "type": "ss", "server": "1.2.3.4", "port": 8388, "data": {"method": "aes-256-gcm", "password": "x"}}
        node_b = {"id": "n-b", "name": "节点B", "type": "ss", "server": "5.6.7.8", "port": 8388, "data": {"method": "aes-256-gcm", "password": "y"}}
        cfg = config_gen.build_config([
            {"enabled": True, "listen": "0.0.0.0", "port": 7890, "node_id": "n-a"},
            {"enabled": True, "listen": "127.0.0.1", "port": 1080, "node_id": "n-b"},
            {"enabled": True, "listen": "0.0.0.0", "port": 7790},
        ], node_a, [node_a, node_b])
        tags = {ob["tag"] for ob in cfg["outbounds"]}
        self.assertIn("node-n-a", tags)
        self.assertIn("node-n-b", tags)
        rules = {r["inbound"][0]: r["outbound"] for r in cfg["route"]["rules"]}
        self.assertEqual(rules["mixed-in-0"], "node-n-a", "指定节点应独立路由")
        self.assertEqual(rules["mixed-in-1"], "node-n-b")
        self.assertEqual(rules["mixed-in-2"], "node-n-a", "未指定时跟随全局节点")
        cfg2 = config_gen.build_config(
            {"enabled": True, "listen": "0.0.0.0", "port": 7890}, None, [node_a])
        self.assertEqual(cfg2["route"]["rules"][0]["outbound"], "direct")

    def test_socks_inbound_auth(self):
        cfg = config_gen.build_config(
            {"listen": "127.0.0.1", "port": 1080, "username": "u", "password": "p"},
            None,
        )
        self.assertEqual(cfg["inbounds"][0]["users"], [{"username": "u", "password": "p"}])

    def test_ss_outbound(self):
        cfg = config_gen.build_config(
            {"listen": "0.0.0.0", "port": 1080, "username": "", "password": ""},
            self._mk("ss", method="aes-256-gcm", password="pwd"),
        )
        ob = cfg["outbounds"][0]
        self.assertEqual(ob["type"], "shadowsocks")
        self.assertEqual(ob["server_port"], 8388)
        self.assertEqual(cfg["route"]["rules"][0]["outbound"], ob["tag"], "入站应路由到节点出站")

    def test_vmess_ws_outbound(self):
        cfg = config_gen.build_config(
            {"listen": "0.0.0.0", "port": 1080},
            self._mk("vmess", port=443, uuid="u1", security="auto", alter_id=0,
                     network="ws", path="/ws", host="h.example.com", tls=True, sni="h.example.com"),
        )
        ob = cfg["outbounds"][0]
        self.assertEqual(ob["type"], "vmess")
        self.assertEqual(ob["transport"]["type"], "ws")
        self.assertEqual(ob["transport"]["path"], "/ws")
        self.assertTrue(ob["tls"]["enabled"])

    def test_vless_reality_outbound(self):
        cfg = config_gen.build_config(
            {"listen": "0.0.0.0", "port": 1080},
            self._mk("vless", port=443, uuid="u2", flow="xtls-rprx-vision",
                     reality=True, pbk="pk", sid="sid", sni="r.example.com", fp="chrome", spx="/"),
        )
        ob = cfg["outbounds"][0]
        self.assertEqual(ob["type"], "vless")
        self.assertTrue(ob["tls"]["reality"]["enabled"])
        self.assertEqual(ob["tls"]["reality"]["public_key"], "pk")
        self.assertNotIn("spider_x", ob["tls"]["reality"], "sing-box 不支持 spider_x 字段")

    def test_hy2_outbound(self):
        cfg = config_gen.build_config(
            {"listen": "0.0.0.0", "port": 1080},
            self._mk("hysteria2", port=8443, password="hp", sni="h.example.com", insecure=True),
        )
        ob = cfg["outbounds"][0]
        self.assertEqual(ob["type"], "hysteria2")
        self.assertTrue(ob["tls"]["insecure"])

    def test_unsupported_falls_back_direct(self):
        cfg = config_gen.build_config(
            {"listen": "0.0.0.0", "port": 1080},
            {"name": "x", "type": "wireguard", "server": "1.2.3.4", "port": 51820, "data": {"unsupported": True}},
        )
        self.assertEqual(cfg["route"]["rules"][0]["outbound"], "direct")


if __name__ == "__main__":
    unittest.main()
