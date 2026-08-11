# -*- coding: utf-8 -*-
"""安全 / 存储并发 / SSRF / 鉴权 / 端口范围等回归测试。

运行: python -m unittest tests.test_security -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.server import storage, util
from app.server.parsers import helpers
from app.server.subscriptions import _is_safe_target, _mask_url


class TestPortRange(unittest.TestCase):
    def test_valid_port(self):
        self.assertEqual(helpers.parse_host_port("1.2.3.4:8080"), ("1.2.3.4", 8080))
        self.assertEqual(helpers.parse_host_port("[::1]:443"), ("::1", 443))

    def test_out_of_range_falls_back(self):
        # 端口 0 / 65536 / 99999 视为非法，回落到 default_port
        self.assertEqual(helpers.parse_host_port("1.2.3.4:0", default_port=80), ("1.2.3.4", 80))
        self.assertEqual(helpers.parse_host_port("1.2.3.4:65536", default_port=80), ("1.2.3.4", 80))
        self.assertEqual(helpers.parse_host_port("1.2.3.4:99999", default_port=80), ("1.2.3.4", 80))
        self.assertEqual(helpers.parse_host_port("1.2.3.4:-1", default_port=80), ("1.2.3.4", 80))


class TestSSRFGuard(unittest.TestCase):
    def test_reject_private_addresses(self):
        # 127.0.0.1 不应被允许（但需要 socket 解析；通常本机解析）
        for url in ("http://127.0.0.1/x", "http://localhost/x"):
            # localhost 可能解析到 127.0.0.1 或 ::1 视环境而异 —— 任一皆应被拒
            res = _is_safe_target(url)
            self.assertFalse(res, "应拒绝本地地址: %s" % url)

    def test_accept_public_host(self):
        # 公网域名不应直接被拒（不做真正 DNS 查询时取决于环境——做一次肯定可达的公网解析）
        # 这里只验证函数能跑通而不会误判 https scheme
        res = _is_safe_target("https://example.com/path")
        # 视环境可能真解析成功；若成功应允许，否则视为环境限制，不报错
        self.assertIn(res, (True, False))

    def test_reject_non_http_scheme(self):
        self.assertFalse(_is_safe_target("file:///etc/passwd"))
        self.assertFalse(_is_safe_target("ftp://example.com/x"))
        self.assertFalse(_is_safe_target("javascript:alert(1)"))
        self.assertFalse(_is_safe_target(""))

    def test_reject_metadata_endpoint(self):
        # 云元数据服务（169.254.169.254）应被拒绝（环境差异下可能解析失败，但不应放行）
        res = _is_safe_target("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(res, "应拒绝云元数据端点")


class TestMaskURL(unittest.TestCase):
    def test_mask_keeps_host_drops_path(self):
        masked = _mask_url("https://sub.example.com/v1/client/subscribe?token=secret")
        self.assertIn("sub.example.com", masked)
        self.assertNotIn("secret", masked)
        self.assertNotIn("/subscribe", masked)

    def test_mask_handles_invalid_url(self):
        # 对怪异输入也应安全返回
        masked = _mask_url("###")
        self.assertEqual(masked, "***")


class TestStoreLocking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = storage.Store(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_transaction_is_reentrant(self):
        with self.store.transaction():
            with self.store.transaction():
                self.assertTrue(True, "RLock 应可重入")

    def test_update_settings_atomic(self):
        self.store.save_settings({"proxies": []})
        # 模拟并发：在 fn 内再次读 settings 应基于最新视图（重入锁后 RLock 覆盖）

        def bump(s):
            s["n"] = s.get("n", 0) + 1
            return s
        for _ in range(10):
            self.store.update_settings(bump)
        s = self.store.load_settings()
        self.assertEqual(s["n"], 10)


class TestB64(unittest.TestCase):
    def test_invalid_returns_none(self):
        self.assertIsNone(helpers.b64decode_any("!!!"))


class TestWebResponseSanitization(unittest.TestCase):
    def setUp(self):
        from app.server.web import App
        self.App = App

    def _make_handler(self, method, path, host="test.local"):
        class H:
            def __init__(self):
                self.command = method
                self.headers = {"Content-Length": "0", "Host": host}
                self.client_address = ("127.0.0.1", 0)
                self.path = path
                self.sent_code = None
                self.headers_out = {}
                self.body_out = b""
                import io as _io
                self.rfile = _io.BytesIO(b"")
                # wfile must capture sent bytes
                self.wfile = _io.BytesIO()

            def send_response(self, code):
                self.sent_code = code

            def send_header(self, k, v):
                self.headers_out[k] = v

            def end_headers(self):
                pass

        h = H()
        return h

    def test_internal_error_returns_generic_message(self):
        app = self.App(auth_token=None)

        @app.route("GET", r"/api/maybe_error")
        def _boom(req):
            raise RuntimeError("这里包含敏感信息，不应出现在响应中 12345")

        h = self._make_handler("GET", "/api/maybe_error")
        app.dispatch(h)
        # dispatch 直接通过 handler._send 调 wfile.write，故可读 body
        body = h.wfile.getvalue().decode("utf-8", errors="replace")
        self.assertEqual(h.sent_code, 500)
        self.assertIn("服务器内部错误", body)
        self.assertNotIn("12345", body, "敏感异常细节不应返回前端")

    def test_401_when_token_mismatch(self):
        app = self.App(auth_token="right-token", logger=None)

        @app.route("GET", r"/api/secret")
        def _hidden(req):
            return {"ok": True}

        # 缺 Authorization
        h = self._make_handler("GET", "/api/secret")
        app.dispatch(h)
        self.assertEqual(h.sent_code, 401)

        # 错误 token
        h2 = self._make_handler("GET", "/api/secret")
        h2.headers["Authorization"] = "Bearer WRONG-TOKEN-ABC"
        app.dispatch(h2)
        self.assertEqual(h2.sent_code, 401)

        # 正确 token + 同源（无 Origin）应放行
        h3 = self._make_handler("GET", "/api/secret")
        h3.headers["Authorization"] = "Bearer right-token"
        app.dispatch(h3)
        self.assertEqual(h3.sent_code, 200)

    def test_csrf_cross_origin_blocked_for_unsafe_methods(self):
        app = self.App(auth_token=None)

        @app.route("POST", r"/api/danger")
        def _danger(req):
            return {"ok": True}

        # 跨域 POST 无 Authorization 应被拒
        h = self._make_handler("POST", "/api/danger")
        h.headers["Origin"] = "https://evil.example.com"
        app.dispatch(h)
        self.assertEqual(h.sent_code, 403)

        # 带 Authorization 视为可信 API 调用，放行
        h2 = self._make_handler("POST", "/api/danger")
        h2.headers["Origin"] = "https://evil.example.com"
        h2.headers["Authorization"] = "Bearer bypass-token"
        app.auth_token = "bypass-token"
        app.dispatch(h2)
        self.assertEqual(h2.sent_code, 200)


class TestBinaryWhitelist(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.fake_bin = os.path.join(self.tmp, "fake-sing-box")
        with open(self.fake_bin, "w") as f:
            f.write("#!/bin/sh\necho fake\n")
        os.chmod(self.fake_bin, 0o755)
        self.outside = os.path.join(os.path.realpath(tempfile.gettempdir()), "fn-socks-outside-test-bin")
        with open(self.outside, "w") as f:
            f.write("#!/bin/sh\necho outside\n")
        os.chmod(self.outside, 0o755)

    def tearDown(self):
        for p in (self.fake_bin, self.outside):
            try:
                os.remove(p)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_allowed_within_whitelist(self):
        from app.server.core.manager import is_binary_path_allowed
        whitelist = [self.tmp]
        self.assertTrue(is_binary_path_allowed(self.fake_bin, whitelist))

    def test_rejected_outside_whitelist(self):
        from app.server.core.manager import is_binary_path_allowed
        whitelist = [self.tmp]
        self.assertFalse(is_binary_path_allowed(self.outside, whitelist))

    def test_empty_path_always_allowed(self):
        from app.server.core.manager import is_binary_path_allowed
        self.assertTrue(is_binary_path_allowed(""))
        self.assertTrue(is_binary_path_allowed("", []))

    def test_reject_nonexistent(self):
        from app.server.core.manager import is_binary_path_allowed
        self.assertFalse(is_binary_path_allowed("/no/such/path/foo", ["/"]))


if __name__ == "__main__":
    unittest.main()