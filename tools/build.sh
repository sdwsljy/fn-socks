#!/bin/bash
# 在 Linux/macOS 上构建 fnOS 应用包（.fpk）
# 依赖: fnpack (https://developer.fnnas.com/docs/cli/fnpack)
set -e
cd "$(dirname "$0")/.."

chmod +x cmd/* tools/*.py tools/*.sh 2>/dev/null || true

if command -v fnpack >/dev/null 2>&1; then
  fnpack build .
else
  echo "未找到 fnpack，请先安装："
  echo "  curl -fsSL -o /usr/local/bin/fnpack https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-amd64"
  echo "  chmod +x /usr/local/bin/fnpack"
  exit 1
fi
