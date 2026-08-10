# -*- coding: utf-8 -*-
"""端到端测试：验证「订阅抓取 → 节点解析 → SOCKS 代理 → 代理转发」全链路。

原理（无需公网节点）：
  1. 用 sing-box 起一个本地 Shadowsocks「服务端」；
  2. 本地 HTTP 服务发布一个 base64 订阅（内含指向该本地 ss 节点的链接）；
  3. 启动本应用后端，通过 API 完成：添加订阅 → 更新 → 选择节点 →
     配置并启用 SOCKS → 通过 SOCKS 访问本地 HTTP 目标；
  4. 若最终能取回目标内容，说明整条链路工作正常。

用法:
  python tests/e2e_test.py --core-path /path/to/sing-box
"""
import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(ROOT, "app", "server", "main.py")
WWW_DIR = os.path.join(ROOT, "app", "www")

SB_SERVER_PORT = 19000
TARGET_PORT = 18001
SUB_PORT = 18002
APP_PORT = 18080
SOCKS_PORT = 18090

SS_PASSWORD = "e2e-pass-123"
SS_METHOD = "aes-256-gcm"
TARGET_BODY = "PASSWALL2-E2E-OK"

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("[PASS] %s" % name)
    else:
        FAIL.append(name)
        print("[FAIL] %s %s" % (name, detail))


def wait_port(host, port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def api(method, path, body=None, port=APP_PORT):
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}


def socks5_request(socks_port, target_host, target_port, path, username="", password=""):
    s = socket.create_connection(("127.0.0.1", socks_port), timeout=10)
    try:
        if username:
            auth = bytes([0x05, 0x01, 0x02])
            s.sendall(auth)
            r = s.recv(2)
            if r[1] != 0x02:
                raise RuntimeError("服务器不支持用户名密码认证")
            u = username.encode("utf-8")
            p = password.encode("utf-8")
            payload = bytes([0x01, len(u)]) + u + bytes([len(p)]) + p
            s.sendall(payload)
            r = s.recv(2)
            if r[1] != 0x00:
                raise RuntimeError("SOCKS 认证失败")
        else:
            s.sendall(bytes([0x05, 0x01, 0x00]))
            r = s.recv(2)
            if r[1] != 0x00:
                raise RuntimeError("SOCKS 免认证失败")
        th = target_host.encode("utf-8")
        req = bytes([0x05, 0x01, 0x00, 0x03, len(th)]) + th + target_port.to_bytes(2, "big")
        s.sendall(req)
        r = s.recv(10)
        if r[1] != 0x00:
            raise RuntimeError("SOCKS CONNECT 被拒绝")
        http = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\n\r\n"
                % (path, target_host, target_port)).encode("utf-8")
        s.sendall(http)
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf
    finally:
        s.close()


class TargetHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(TARGET_BODY)))
        self.end_headers()
        self.wfile.write(TARGET_BODY.encode("utf-8"))

    def log_message(self, *a):
        pass


class SubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        userinfo = base64.b64encode(("aes-256-gcm:%s" % SS_PASSWORD).encode("utf-8")).decode("ascii")
        links = "ss://%s@127.0.0.1:%d#E2E-Local-Node\n" % (userinfo, SB_SERVER_PORT)
        body = base64.b64encode(links.encode("utf-8")).decode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Subscription-Userinfo", "upload=1048576; download=2097152; total=10737418240; expire=2000000000")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *a):
        pass


def start_http(handler_cls, port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def make_ss_server_config(path):
    cfg = {
        "log": {"level": "warn"},
        "inbounds": [{
            "type": "shadowsocks",
            "tag": "ss-in",
            "listen": "127.0.0.1",
            "listen_port": SB_SERVER_PORT,
            "method": SS_METHOD,
            "password": SS_PASSWORD,
        }],
        "outbounds": [{"type": "direct", "tag": "direct"}],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core-path", required=True, help="sing-box 可执行文件路径")
    args = ap.parse_args()

    sb = os.path.abspath(args.core_path)
    if not os.path.isfile(sb):
        print("错误: sing-box 不存在: %s" % sb)
        return 1

    tmp = tempfile.mkdtemp(prefix="pw2-e2e-")
    procs = []
    servers = []
    try:
        server_cfg = os.path.join(tmp, "ss-server.json")
        make_ss_server_config(server_cfg)
        p1 = subprocess.Popen([sb, "run", "-c", server_cfg],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p1)
        check("本地 ss 服务端启动", wait_port("127.0.0.1", SB_SERVER_PORT))

        servers.append(start_http(TargetHandler, TARGET_PORT))
        servers.append(start_http(SubHandler, SUB_PORT))
        check("本地 HTTP 服务就绪", wait_port("127.0.0.1", TARGET_PORT) and wait_port("127.0.0.1", SUB_PORT))

        app_data = os.path.join(tmp, "appdata")
        os.makedirs(app_data)
        app_log = open(os.path.join(tmp, "app-stdout.log"), "wb")
        p2 = subprocess.Popen(
            [sys.executable, MAIN_PY,
             "--host", "127.0.0.1", "--port", str(APP_PORT),
             "--data-dir", app_data, "--www-dir", WWW_DIR,
             "--core-path", sb, "--log-level", "debug"],
            stdout=app_log, stderr=subprocess.STDOUT,
        )
        procs.append(p2)
        check("应用后端启动", wait_port("127.0.0.1", APP_PORT))

        r = api("POST", "/api/subscriptions", {"url": "http://127.0.0.1:%d/sub" % SUB_PORT, "remark": "E2E"})
        check("添加订阅", r.get("ok") is True, json.dumps(r, ensure_ascii=False))
        sub_id = r.get("subscription", {}).get("id")

        r = api("POST", "/api/subscriptions/%s/update" % sub_id)
        check("更新订阅", r.get("ok") is True and r.get("nodes") == 1, json.dumps(r, ensure_ascii=False))
        check("订阅套餐信息解析", (r.get("info") or {}).get("total") == "10737418240", json.dumps(r, ensure_ascii=False))

        r = api("GET", "/api/nodes")
        nodes = r.get("nodes") or []
        check("节点列表含 1 个节点", len(nodes) == 1, json.dumps(r, ensure_ascii=False))
        node = nodes[0] if nodes else {}
        check("节点字段正确",
              node.get("type") == "ss" and node.get("server") == "127.0.0.1" and node.get("port") == SB_SERVER_PORT,
              json.dumps(node, ensure_ascii=False))
        check("节点名称解析", node.get("name") == "E2E-Local-Node", json.dumps(node, ensure_ascii=False))
        node_id = node.get("id")

        r = api("POST", "/api/nodes/%s/select" % node_id)
        check("设为当前节点", r.get("ok") is True)

        r = api("PUT", "/api/config/socks", {
            "enabled": True, "listen": "127.0.0.1", "port": SOCKS_PORT,
            "username": "", "password": "",
        })
        check("保存 SOCKS 配置", r.get("ok") is True, json.dumps(r, ensure_ascii=False))
        r = api("POST", "/api/config/socks/apply")
        check("应用 SOCKS 配置", r.get("ok") is True, json.dumps(r, ensure_ascii=False))
        check("代理核心运行中", wait_port("127.0.0.1", SOCKS_PORT))

        try:
            resp = socks5_request(SOCKS_PORT, "127.0.0.1", TARGET_PORT, "/hello.txt")
            ok = TARGET_BODY.encode("utf-8") in resp
            check("免认证：通过 SOCKS 取回目标内容", ok, resp[:200].decode("utf-8", "replace"))
        except Exception as e:
            check("免认证：通过 SOCKS 取回目标内容", False, str(e))

        r = api("PUT", "/api/config/socks", {
            "enabled": True, "listen": "127.0.0.1", "port": SOCKS_PORT,
            "username": "admin", "password": "secret",
        })
        api("POST", "/api/config/socks/apply")
        time.sleep(1.0)
        try:
            socks5_request(SOCKS_PORT, "127.0.0.1", TARGET_PORT, "/")
            check("认证模式：无认证应被拒绝", False, "意外成功")
        except Exception:
            check("认证模式：无认证应被拒绝", True)
        try:
            resp = socks5_request(SOCKS_PORT, "127.0.0.1", TARGET_PORT, "/hello.txt",
                                  username="admin", password="secret")
            check("认证模式：正确认证可访问", TARGET_BODY.encode("utf-8") in resp)
        except Exception as e:
            check("认证模式：正确认证可访问", False, str(e))

        r = api("GET", "/api/status")
        check("状态接口核心信息", (r.get("core") or {}).get("running") is True, json.dumps(r, ensure_ascii=False))
    finally:
        for srv in servers:
            try:
                srv.shutdown()
            except Exception:
                pass
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

    print("\n===== E2E 结果: %d 通过, %d 失败 =====" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:", " | ".join(FAIL))
        return 1
    print("全部通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
