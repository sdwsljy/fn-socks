# -*- coding: utf-8 -*-
"""本地开发运行脚本（无需 fnOS 环境）。"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))


def main():
    p = argparse.ArgumentParser(description="fn-cocks local dev")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--core-path", default="")
    p.add_argument("--auth-token", default="")
    p.add_argument("--data-dir", default=os.path.join(ROOT, "dev-data"))
    args = p.parse_args()

    from server.main import main as server_main

    sys.argv = [
        "main.py",
        "--host", args.host,
        "--port", str(args.port),
        "--data-dir", args.data_dir,
        "--www-dir", os.path.join(ROOT, "app", "www"),
        "--core-path", args.core_path,
    ]
    if args.auth_token:
        sys.argv += ["--auth-token", args.auth_token]
    sys.exit(server_main())


if __name__ == "__main__":
    main()
