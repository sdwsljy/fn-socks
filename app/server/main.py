# -*- coding: utf-8 -*-
"""fn-cocks — 后端入口。

用法:
  python main.py [--host 0.0.0.0] [--port 8080] [--data-dir ./data]
                 [--www-dir ../www] [--core-path sing-box] [--auth-token TOKEN]
                 [--unix-socket PATH]
"""
import argparse
import os
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
        logger.info("核心自启动: %s" % msg)
    except Exception as e:
        logger.error("核心自启动异常: %s" % e)


def build_parser():
    p = argparse.ArgumentParser(description="fn-cocks backend")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--www-dir", default=None)
    p.add_argument("--core-path", default="")
    p.add_argument("--auth-token", default="")
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
    logger.info("===== fn-cocks 后端启动 =====")
    logger.info("数据目录: %s" % data_dir)

    store = Store(data_dir)
    subs = SubscriptionManager(store, logger)
    core = CoreManager(os.path.join(data_dir, "core"), core_binary=args.core_path, logger=logger)

    # 从设置读取核心路径（优先于启动参数）
    settings = store.load_settings()
    saved_binary = settings.get("core", {}).get("binary")
    if saved_binary:
        core.set_binary(saved_binary)

    ctx = api_mod.AppContext(
        store=store,
        subs=subs,
        core=core,
        logger=logger,
        core_log_path=core_log,
        app_log_path=app_log,
    )

    app = App(auth_token=args.auth_token or None, logger=logger)
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
        core.stop(wait=False)
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
