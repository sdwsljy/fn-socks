# -*- coding: utf-8 -*-
"""fn-socks — 后端入口。

用法:
  python main.py [--host 0.0.0.0] [--port 8080] [--data-dir ./data]
                 [--www-dir ../www] [--core-path sing-box]
                 [--auth-token TOKEN | --auth-token-file FILE]
                 [--no-auto-token] [--unix-socket PATH]
"""
import argparse
import os
import secrets
import signal
import sys
import time

# 支持以脚本方式直接运行（python main.py），等价于包内运行
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "server"

from . import api as api_mod
from . import util
from .core.manager import CoreManager
from .logger import get_logger
from .storage import Store
from .subscriptions import SubscriptionManager
from .web import App, Server

DEFAULT_PORT = 8080
TOKEN_FILE = "auth_token"  # 存放在 data_dir 顶层


def _resolve_auth_token(args, data_dir, logger):
    """决定本次使用的 auth_token：

    优先级：--auth-token > --auth-token-file > data_dir/auth_token > 自动生成并持久化。
    --no-auto-token 显式禁用鉴权（仅本地 dev 使用，强烈不建议生产开启）。
    """
    if args.no_auto_token:
        logger.warn("已通过 --no-auto-token 禁用 Web 鉴权，存在严重安全风险")
        return None
    if args.auth_token:
        return args.auth_token
    if args.auth_token_file:
        try:
            with open(args.auth_token_file, "r", encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t
        except OSError as e:
            logger.warn("读取 --auth-token-file 失败: %s" % e)
    token_path = os.path.join(data_dir, TOKEN_FILE)
    try:
        if os.path.isfile(token_path):
            with open(token_path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                return existing
    except OSError:
        pass
    # 自动生成并持久化：用户首次启动从该文件取出
    new_token = secrets.token_urlsafe(24)
    try:
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(new_token)
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass
    except OSError as e:
        logger.error("持久化 auth_token 失败: %s" % e)
    logger.warn("首次启动：已自动生成访问令牌并写入 %s" % token_path)
    logger.warn("API 调用需在请求头携带：Authorization: Bearer <token>")
    return new_token


def auto_start_core(store, core, logger):
    """核心自启动：后端启动时自动恢复代理核心。

    读取设置中的代理配置，若存在启用的代理条目且有可用节点，
    则自动生成配置并启动 sing-box 核心（等价于用户在页面上点击「应用」）。
    失败仅记录日志，不阻断后端启动。
    """
    try:
        settings = store.load_settings()
        proxies = settings.get("proxies") or []
        enabled = [p for p in proxies if p.get("enabled")]
        if not enabled:
            logger.info("核心自启动: 无启用的代理配置，跳过")
            return
        nodes = store.load_nodes()
        node, err = api_mod.resolve_active_node(store, settings, proxies, nodes, logger)
        if err:
            logger.warn("核心自启动跳过: %s" % err)
            return
        ok, msg = core.apply(proxies, node, nodes)
        if ok:
            logger.info("核心自启动: %s" % msg)
        else:
            logger.error("核心自启动失败: %s" % msg)
    except Exception as e:
        logger.error("核心自启动异常: %s" % e)


def build_parser():
    p = argparse.ArgumentParser(description="fn-socks backend")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--www-dir", default=None)
    p.add_argument("--core-path", default="")
    p.add_argument("--auth-token", default="",
                   help="显式指定 Web 访问令牌；优先级最高")
    p.add_argument("--auth-token-file", default="",
                   help="从文件读取 Web 访问令牌")
    p.add_argument("--no-auto-token", action="store_true",
                   help="禁用 Web 鉴权（仅 dev 用，存在严重安全风险）")
    p.add_argument("--unix-socket", default="")
    p.add_argument("--log-level", default="info")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    data_dir = os.path.abspath(args.data_dir)
    util.ensure_dir(data_dir)

    app_log = os.path.join(data_dir, "logs", "app.log")
    core_log = os.path.join(data_dir, "logs", "core.log")
    logger = get_logger(app_log, args.log_level, "app")
    logger.info("===== fn-socks 后端启动 =====")
    logger.info("数据目录: %s" % data_dir)

    store = Store(data_dir)
    subs = SubscriptionManager(store, logger)
    core = CoreManager(os.path.join(data_dir, "core"), core_binary=args.core_path, logger=logger)

    # 从设置读取核心路径（优先于启动参数；启动参数必须是白名单内）
    settings = store.load_settings()
    saved_binary = settings.get("core", {}).get("binary")
    if saved_binary:
        core.set_binary(saved_binary)

    auth_token = _resolve_auth_token(args, data_dir, logger)

    ctx = api_mod.AppContext(
        store=store,
        subs=subs,
        core=core,
        logger=logger,
        core_log_path=core_log,
        app_log_path=app_log,
        auth_token=auth_token,
    )

    app = App(auth_token=auth_token, logger=logger)
    if args.www_dir and os.path.isdir(args.www_dir):
        app.serve_static(os.path.abspath(args.www_dir), "/")
        logger.info("静态目录: %s" % os.path.abspath(args.www_dir))
    api_mod.register_routes(app, ctx)

    server = Server(
        app,
        host=args.host,
        port=args.port,
        unix_socket=args.unix_socket or None,
        logger=logger,
    )
    server.start()
    logger.info("监听: %s:%d" % (args.host, args.port))

    # 订阅自动更新调度（按 sub.interval_min 触发）
    subs.start_auto_updater()

    # 核心自启动：后端启动时自动恢复代理核心（有启用代理且存在节点时）
    auto_start_core(store, core, logger)

    stop_flag = [False]

    def _on_signal(signum, frame):
        stop_flag[0] = True

    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
    except (ValueError, OSError):
        pass

    try:
        while not stop_flag[0]:
            time.sleep(0.5)
    finally:
        logger.info("收到退出信号，正在停止代理核心并关闭服务...")
        subs.stop_auto_updater()
        core.stop(wait=False)
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())