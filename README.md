# fn-cocks

基于 [PassWall2](https://github.com/Openwrt-Passwall/openwrt-passwall2) 设计思路实现的飞牛私有云（fnOS）应用，核心能力：

- **节点订阅**：添加 / 更新 / 删除订阅，自动识别并解析常见订阅格式
- **SOCKS5 / HTTP 代理**：基于 sing-box 的 mixed 入站，同一端口同时提供 SOCKS5 与 HTTP 代理；支持**多端口**配置，每条代理可**指定独立出口节点**

完全离线可用：后端为 Python 标准库实现（零 pip 依赖），前端为原生 HTML/CSS/JS，不加载任何 CDN 资源。

---

## 功能特性

| 模块 | 说明 |
| --- | --- |
| 节点订阅 | 支持 base64 链接（ss / ssr / vmess / vless / trojan / hysteria2 / tuic / socks5）、Clash YAML、sing-box JSON、SSD 格式；可设置自定义 User-Agent、定时自动更新；展示套餐流量 / 到期时间（`subscription-userinfo` 头） |
| 节点管理 | 节点列表、搜索 / 分组过滤、手动导入分享链接、TCP 测速、设置当前节点、**自定义节点名称**（订阅更新时自动保留） |
| 代理配置 | 支持**多端口**代理条目（新增 / 编辑 / 删除 / 独立开关），每条可设置监听地址、端口、用户名密码认证，并**指定独立出口节点**（不指定则跟随全局当前节点）；一键应用并重启核心；每个端口同一时间支持 SOCKS5 与 HTTP |
| 运行日志 | 代理核心日志与服务日志实时查看 |

## 架构

```
┌──────────────────────────── fnOS (Debian) ────────────────────────────┐
│   Web 界面 (app/www, 原生 HTML/JS)                                    │
│        │  HTTP :15666                                                 │
│   Python 后端 (app/server, 纯标准库)                                   │
│        ├─ 订阅抓取与解析 (parsers/)                                    │
│        ├─ 配置生成 (core/config_gen.py)  → sing-box 配置 JSON          │
│        └─ 进程管理 (core/manager.py)      → 启停 sing-box              │
│                                              │                        │
│   sing-box (app/bin, 内置) ─── SOCKS5/HTTP 混合入站（多端口）          │
└───────────────────────────────────────────────────────────────────────┘
```

数据目录（`$TRIM_PKGVAR`）存放 `subscriptions.json`、`nodes.json`、`settings.json` 与日志。

## 目录结构

```
fn-cocks/
├── manifest                 # fnOS 应用清单
├── ICON.PNG / ICON_256.PNG  # 应用图标（64 / 256，tools/build_icons.py 生成）
├── LICENSE
├── config/
│   ├── privilege            # 权限声明
│   └── resource
├── cmd/                     # 生命周期脚本：main / install_* / uninstall_* / upgrade_* / config_*
├── app/
│   ├── ui/config            # 桌面入口（iframe → :15666）
│   ├── www/                 # Web 前端
│   ├── server/              # Python 后端
│   └── bin/                 # sing-box 二进制（随 .fpk 内置分发，请自行放置）
├── tools/
│   ├── build.sh             # Linux/macOS 打包脚本
│   ├── build_icons.py       # 图标生成（纯标准库）
│   └── run_dev.py           # 本地开发运行
└── tests/
    ├── test_parsers.py      # 解析器 / 配置生成单元测试
    └── e2e_test.py          # 端到端全链路测试
```

## 在 fnOS 上安装

> **重要**：请务必在 **Linux / macOS** 环境打包（`tools/build.sh`），不要直接在
> Windows 上用 fnpack 打包——Windows 文件系统没有 Unix 执行位，会导致包内
> `cmd/*` 脚本丢失可执行权限，飞牛安装时提示「执行脚本出错」。

1. 准备 sing-box 二进制（linux-amd64）并安装官方打包工具 `fnpack`（[下载](https://developer.fnnas.com/docs/cli/fnpack)）：

   ```bash
   cd fn-cocks
   # 将 sing-box 放到 app/bin/sing-box（默认 x86 平台）
   curl -fsSL -o /tmp/sb.tgz https://github.com/SagerNet/sing-box/releases/download/v1.11.3/sing-box-1.11.3-linux-amd64.tar.gz
   tar -xzf /tmp/sb.tgz -C /tmp && cp /tmp/sing-box-1.11.3-linux-amd64/sing-box app/bin/sing-box
   python3 tools/build_icons.py   # 生成图标
   chmod +x cmd/* tools/*.py tools/*.sh
   fnpack build .                # 生成 fn-cocks.fpk
   ```

2. 将 `.fpk` 上传到飞牛系统：**应用中心 → 本地安装**，或 SSH 执行
   `appcenter-cli install-fpk fn-cocks.fpk --volume 1`。

3. 安装完成后（见 `cmd/install_init`）：检查 `python3`，校验内置 sing-box 核心（无需联网下载）。

4. 打开应用（Web 端口 **15666**）→ **节点订阅 → 添加订阅** → 粘贴机场订阅链接 →
   更新；再到 **节点列表** 选择当前节点，在 **代理配置** 中启用并应用（SOCKS5 / HTTP 同一端口）。

> 平台说明：当前安装包内含 **linux-amd64** 的 sing-box（`manifest` 中 `platform=x86`）。
> ARM 设备请替换 `app/bin/sing-box` 为对应架构二进制后重新打包。

## 本地开发 / 验证（无需 fnOS）

```bash
# 1. 单元测试
python -m unittest tests.test_parsers -v

# 2. 端到端测试（需 sing-box 二进制）
python tests/e2e_test.py --core-path /path/to/sing-box

# 3. 启动服务（需 Python 3.8+）
python tools/run_dev.py --port 15666
# 浏览器打开 http://127.0.0.1:15666
```

## REST API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/status` | 服务与核心状态 |
| GET/POST | `/api/subscriptions` | 订阅列表 / 添加订阅 |
| PUT/DELETE | `/api/subscriptions/{id}` | 修改 / 删除订阅 |
| POST | `/api/subscriptions/{id}/update` | 更新单个订阅 |
| POST | `/api/subscriptions/update_all` | 更新全部订阅 |
| GET | `/api/nodes` | 节点列表（支持 `sub_id` / `group` / `q` 过滤） |
| POST | `/api/nodes/import` | 导入分享链接 `{text, group}` |
| DELETE | `/api/nodes/{id}` | 删除节点 |
| PUT | `/api/nodes/{id}` | 自定义节点名称 `{name}`（空串恢复原始名称） |
| POST | `/api/nodes/{id}/select` | 设为当前节点 |
| POST | `/api/nodes/{id}/test` | TCP 测速 |
| GET/POST | `/api/config/proxies` | 代理条目列表 / 新增 |
| PUT/DELETE | `/api/config/proxies/{id}` | 修改 / 删除代理条目 |
| POST | `/api/config/proxies/apply` | 应用全部代理配置并重启核心 |
| GET | `/api/core/status` | 核心状态 |
| POST | `/api/core/start\|stop\|restart` | 核心控制 |
| GET | `/api/logs?source=core\|app` | 日志尾部 |

## 安全提示

- SOCKS5 / HTTP 协议本身不加密：监听地址请优先使用 `127.0.0.1`；对外暴露时务必设置用户名 / 密码。
- 如需为 Web 界面加访问令牌：在 `cmd/main` 的启动命令追加 `--auth-token <口令>`，前端 API 将要求 `Authorization: Bearer <口令>`。

## 与 PassWall2 的对应关系

| PassWall2 (OpenWrt) | 本应用 |
| --- | --- |
| `subscribe.lua`（订阅解析） | `app/server/parsers/` + `subscriptions.py` |
| `config socks` / `node_socks_port` | `settings.json → proxies` |
| `util_sing-box.lua gen_config` | `app/server/core/config_gen.py` |
| `app.sh run_socks` | `app/server/core/manager.py` |
| UCI 配置库 | JSON 存储（`$TRIM_PKGVAR`） |

## 已知限制

- Clash YAML 由内置轻量解析器处理（优先使用系统 PyYAML），极少数复杂写法可能解析失败。
- 未实现 PassWall2 的透明代理 / iptables 分流 / ACL 等 OpenWrt 特有能力，本应用聚焦「订阅 + 代理」。
- kcp / quic 等小众传输依赖 sing-box 原生支持，个别参数可能不兼容，以核心日志为准。

## License

MIT
