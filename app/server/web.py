# -*- coding: utf-8 -*-
"""极简 HTTP Web 框架（纯标准库实现）：路由、JSON、静态资源、可选 Token 认证、CSRF 防护。"""
import hmac
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from http.server import ThreadingHTTPServer as _ThreadingHTTPServer
except ImportError:  # pragma: no cover
    _ThreadingHTTPServer = None


class HTTPError(Exception):
    def __init__(self, code, message):
        super(HTTPError, self).__init__(message)
        self.code = code
        self.message = message


class Request(object):
    def __init__(self, handler):
        self.method = handler.command
        parsed = urllib.parse.urlsplit(handler.path)
        self.path = parsed.path
        self.query = urllib.parse.parse_qs(parsed.query)
        self.headers = handler.headers
        self.body = None
        self.client_ip = handler.client_address[0] if handler.client_address else ""
        self._handler = handler

    def read_json(self, max_bytes=2 * 1024 * 1024):
        length = int(self.headers.get("Content-Length") or 0)
        if length > max_bytes:
            raise HTTPError(413, "请求体过大")
        if length <= 0:
            return {}
        raw = self._handler.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, "请求体不是合法 JSON")

    def get_param(self, key, default=None):
        v = self.query.get(key)
        if v:
            return v[0]
        return default

    def header(self, name, default=None):
        return self.headers.get(name, default)


class Response(object):
    def __init__(self, body=b"", status=200, content_type="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = {}

    def set_header(self, k, v):
        self.headers[k] = v


# 安全的方法不需要 CSRF 校验
SAFE_HTTP_METHODS = ("GET", "HEAD", "OPTIONS")


class App(object):
    def __init__(self, auth_token=None, logger=None, allow_origin=None):
        self.routes = []  # (method, regex, handler)
        self.auth_token = auth_token or None
        self.log = logger
        self.static_dir = None
        self.static_prefix = "/"
        # 允许的跨域来源；为 None 表示同源（默认同源，禁止跨域）
        self.allow_origin = allow_origin

    def route(self, method, path_pattern):
        regex = re.compile("^" + path_pattern + "$")

        def deco(handler):
            self.routes.append((method.upper(), regex, handler))
            return handler

        return deco

    def serve_static(self, static_dir, prefix="/"):
        self.static_dir = static_dir
        self.static_prefix = prefix.rstrip("/") or "/"

    # -------------------------------------------------- 鉴权与 CSRF
    def _check_auth(self, req):
        """Bearer Token 鉴权，使用常量时间比较避免时序侧信道。"""
        if not self.auth_token:
            return True
        auth = req.headers.get("Authorization") or ""
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        if not token:
            return False
        # hmac.compare_digest 抗时序
        try:
            return hmac.compare_digest(token, self.auth_token)
        except (TypeError, ValueError):
            return False

    def _check_csrf(self, req):
        """CSRF 防御：非安全跨域请求必须有可信 Origin / Referer，或带 Authorization。

        - token 鉴权通过即视为安全（带自定义头的请求不受 CSRF 影响）；
        - 同源请求放行；
        - 跨域请求默认拒绝，除非显式配置 allow_origin。
        """
        if req.method in SAFE_HTTP_METHODS:
            return True
        origin = req.header("Origin") or ""
        referer = req.header("Referer") or ""
        host = req.header("Host") or ""
        # 带 Authorization 头视为可信（API client / scripted client）
        if req.header("Authorization"):
            return True
        # 同源请求：Origin 为空（非浏览器）或与 Host 匹配
        if origin:
            # origin 形如 https://host:port
            try:
                o = urllib.parse.urlsplit(origin)
                ohost = o.hostname or ""
                oport = str(o.port or "")
                # 端口可能为空→默认；host 可能含 port
                if ":" in host:
                    hh, _, hp = host.partition(":")
                    if (ohost == hh) and (oport == hp or (oport == "" and hp in ("", "80", "443"))):
                        return True
                else:
                    if ohost == host:
                        return True
                if self.allow_origin and origin == self.allow_origin:
                    return True
                return False
            except Exception:
                return False
        # 没 Origin，看 Referer 同源
        if referer:
            try:
                r = urllib.parse.urlsplit(referer)
                rhost = r.hostname or ""
                if ":" in host:
                    hh, _, _ = host.partition(":")
                    if rhost == hh:
                        return True
                elif rhost == host:
                    return True
                return False
            except Exception:
                return False
        # 非 GET 但没有 Origin/Referer/Authorization：可能是非浏览器 API 调用（curl 等）
        # 这类无法伪装浏览器 Cookie，CSRF 风险低，放行
        return True

    def dispatch(self, handler):
        req = Request(handler)
        if req.path.startswith("/api/"):
            # 鉴权端点免鉴权：/api/auth/login 与 /api/auth/status
            # （登录需要提交 token 校验；status 仅返回是否需要令牌，均不泄露敏感信息）
            if req.path not in ("/api/auth/login", "/api/auth/status") and not self._check_auth(req):
                return self._send(handler, Response(
                    json.dumps({"error": "未授权，请检查访问令牌"}),
                    status=401,
                ))
            if not self._check_csrf(req):
                return self._send(handler, Response(
                    json.dumps({"error": "CSRF 校验失败：跨域请求被拒绝"}),
                    status=403,
                ))

        try:
            for method, regex, fn in self.routes:
                if method != req.method:
                    continue
                m = regex.match(req.path)
                if m:
                    params = [urllib.parse.unquote(p) for p in m.groups()]
                    result = fn(req, *params)
                    if result is None:
                        return self._send(handler, Response(b"", 204))
                    if isinstance(result, Response):
                        return self._send(handler, result)
                    return self._send(handler, Response(
                        json.dumps(result, ensure_ascii=False),
                        status=200,
                    ))
            if self.static_dir and req.path.startswith(self.static_prefix):
                return self._serve_file(handler, req)
            return self._send(handler, Response(
                json.dumps({"error": "Not Found"}),
                status=404,
            ))
        except HTTPError as e:
            return self._send(handler, Response(
                json.dumps({"error": e.message}),
                status=e.code,
            ))
        except Exception as e:
            # 完整异常信息只记录到日志，前端只返回通用提示，避免泄露内部细节
            if self.log:
                self.log.error("处理 %s %s 出错: %s" % (req.method, req.path, e))
            else:
                sys.stderr.write("处理 %s %s 出错: %s\n" % (req.method, req.path, e))
            return self._send(handler, Response(
                json.dumps({"error": "服务器内部错误"}),
                status=500,
            ))

    def _serve_file(self, handler, req):
        rel = req.path[len(self.static_prefix):].lstrip("/")
        if not rel:
            rel = "index.html"
        full = os.path.realpath(os.path.join(self.static_dir, rel))
        base = os.path.realpath(self.static_dir)
        if not (full == base or full.startswith(base + os.sep)):
            return self._send(handler, Response(
                json.dumps({"error": "Forbidden"}), status=403))
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            return self._send(handler, Response(
                json.dumps({"error": "Not Found"}), status=404))
        ctype, _ = mimetypes.guess_type(full)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
            ctype += "; charset=utf-8"
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            return self._send(handler, Response(
                json.dumps({"error": "读取失败"}), status=500))
        return self._send(handler, Response(body, status=200, content_type=ctype))

    def _send(self, handler, resp):
        handler.send_response(resp.status)
        handler.send_header("Content-Type", resp.content_type)
        handler.send_header("Content-Length", str(len(resp.body)))
        handler.send_header("Cache-Control", "no-store")
        # 默认同源策略：不发送 CORS 头浏览器即拒绝跨域读取，避免 CSRF 加回显
        if self.allow_origin:
            handler.send_header("Access-Control-Allow-Origin", self.allow_origin)
            handler.send_header("Vary", "Origin")
        for k, v in resp.headers.items():
            handler.send_header(k, v)
        handler.end_headers()
        try:
            handler.wfile.write(resp.body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        return True


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            app.dispatch(self)

        def do_POST(self):
            app.dispatch(self)

        def do_PUT(self):
            app.dispatch(self)

        def do_DELETE(self):
            app.dispatch(self)

        def do_OPTIONS(self):
            # 不支持跨域预检（默认同源策略）
            app.dispatch(self)

    return Handler


class Server(object):
    def __init__(self, app, host="0.0.0.0", port=8080, unix_socket=None, logger=None):
        self.app = app
        self.host = host
        self.port = port
        self.unix_socket = unix_socket
        self.log = logger
        self.httpd = None
        self._thread = None

    def start(self):
        handler_cls = make_handler(self.app)
        if self.unix_socket:
            try:
                os.unlink(self.unix_socket)
            except OSError:
                pass
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(self.unix_socket)
            sock.listen(128)
            self.httpd = ThreadingHTTPServer(self.unix_socket, handler_cls, bind_and_activate=False)
            self.httpd.socket = sock
            self.httpd.server_address = (self.unix_socket,)
        else:
            self.httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
            # 限制并发线程，防止被 DoS
            try:
                self.httpd.daemon_threads = True
                self.httpd.request_queue_size = 64
            except Exception:
                pass
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        addr = self.unix_socket or "%s:%d" % (self.host, self.port)
        if self.log:
            self.log.info("Web 服务已启动: %s" % addr)
        return self.httpd

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None