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
