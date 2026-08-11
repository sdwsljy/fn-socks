# -*- coding: utf-8 -*-
"""sing-box 进程管理：启动 / 停止 / 重启 / 状态查询。"""
import json
import os
import signal
import subprocess
import sys
import threading
import time

from .. import util
from ..logger import get_logger
from . import config_gen

try:
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW  # Windows
except AttributeError:  # pragma: no cover
    CREATE_NO_WINDOW = 0


def _default_binary_whitelist():
    """允许的核心二进制所在目录白名单。可通过环境变量扩展。"""
    env_dirs = os.environ.get("FN_SOCKS_BIN_WHITELIST", "")
    dirs = [d for d in env_dirs.split(os.pathsep) if d]
    # 飞牛打包内置目录
    appdest = os.environ.get("TRIM_APPDEST", "")
    if appdest:
        dirs.append(os.path.join(appdest, "bin"))
    # 常见系统安装位置
    dirs.extend(["/usr/local/bin", "/usr/bin", "/opt/sing-box", "/opt/fn-socks/bin"])
    # 开发运行目录
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dirs.append(os.path.join(here, "bin"))
    # 去重保序
    seen = set()
    out = []
    for d in dirs:
        d = os.path.realpath(d)
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def is_binary_path_allowed(path, whitelist=None):
    """校验 core_binary 路径是否在白名单目录内；空路径放行（用默认查找）。"""
    if not path:
        return True
    if not os.path.isabs(path):
        # 相对路径在 root 后端运行时可能被解析为敏感位置，拒绝
        return False
    try:
        rp = os.path.realpath(path)
        if not os.path.isfile(rp):
            return False
    except OSError:
        return False
    whitelist = whitelist if whitelist is not None else _default_binary_whitelist()
    parent = os.path.dirname(rp)
    for d in whitelist:
        if parent == d:
            return True
    return False


class CoreManager(object):
    def __init__(self, work_dir, core_binary=None, logger=None, binary_whitelist=None):
        self.work_dir = util.ensure_dir(work_dir)
        self.log = logger or get_logger(tag="core")
        # CLI 提供的核心路径（来自 --core-path）：由 root 启动时设置，非外部攻击面，
        # 不受白名单约束；set_binary() 提供的路径受白名单约束。
        self.core_binary = core_binary or ""
        self._cli_binary = core_binary or ""
        self.pid_file = os.path.join(self.work_dir, "core.pid")
        self.config_file = os.path.join(self.work_dir, "config.json")
        self.core_log = os.path.join(self.work_dir, "core.log")
        self._proc = None
        self._lock = threading.RLock()
        self._last_error = None
        self._version = None
        self._binary_whitelist = binary_whitelist if binary_whitelist is not None else _default_binary_whitelist()

    def find_binary(self, candidates=None):
        """查找核心二进制：候选路径必须存在且可执行。

        - 候选路径优先（candidates 来自 CLI `--core-path` 初始值或经 `set_binary` 已校验白名单的设置值）
        - 之后回退到白名单目录扫描，按优先级选择 sing-box
        """
        cands = list(candidates) if candidates else []
        # 1. 候选路径（CLI / settings，均已完成信任判定）
        for c in cands:
            if not c:
                continue
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        # 2. 兜底：在白名单目录中扫描
        for d in self._binary_whitelist:
            for name in ("sing-box", "sing-box.exe"):
                p = os.path.join(d, name)
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    return p
        return None

    def set_binary(self, path):
        """通过 API 设置的核心路径：必须通过白名单校验以防止任意命令执行。"""
        if path and not is_binary_path_allowed(path, self._binary_whitelist):
            self.log.warn("拒绝设置核心路径，超出白名单: %s" % path)
            return False
        self.core_binary = path or ""
        return True

    @property
    def binary(self):
        return self.find_binary([self.core_binary]) or ""

    def is_running(self):
        pid = self._read_pid()
        if pid:
            if self._proc and self._proc.pid == pid and self._proc.poll() is None:
                return True
            if self._pid_alive(pid):
                return True
        self._clear_pid()
        if self._proc is not None and self._proc.poll() is None:
            return True
        return False

    def _read_pid(self):
        try:
            with open(self.pid_file, "r") as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    def _write_pid(self, pid):
        try:
            with open(self.pid_file, "w") as f:
                f.write(str(pid))
        except OSError as e:
            self.log.warn("写入 pid 文件失败: %s" % e)

    def _clear_pid(self):
        try:
            if os.path.isfile(self.pid_file):
                os.remove(self.pid_file)
        except OSError as e:
            self.log.warn("清理 pid 文件失败: %s" % e)

    def _pid_alive(self, pid):
        if not pid or pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
                if not h:
                    return False
                exit_code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(h)
                return exit_code.value == 259  # STILL_ACTIVE
            except OSError:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def version(self):
        if self._version:
            return self._version
        binary = self.binary
        if not binary:
            return None
        try:
            out = subprocess.run(
                [binary, "version"], capture_output=True, timeout=10, text=True
            )
            ver = (out.stdout or out.stderr or "").strip()
            self._version = ver.splitlines()[0] if ver else None
            return self._version
        except (OSError, subprocess.SubprocessError):
            return None

    def generate_config(self, proxies_cfg, active_node, nodes=None):
        return config_gen.build_config(proxies_cfg, active_node, nodes, log_file=self.core_log)

    def write_config(self, cfg):
        cfg_json = config_gen.config_to_json(cfg)
        util.ensure_dir(os.path.dirname(self.config_file))
        tmp = self.config_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(cfg_json)
        os.replace(tmp, self.config_file)
        return self.config_file

    def apply(self, proxies_cfg, active_node, nodes=None):
        binary = self.binary
        if not binary:
            self._last_error = "未找到 sing-box 可执行文件，请在设置中配置核心路径或重新安装"
            return False, self._last_error
        # 统一入口：proxies_cfg 始终规整为 list；不再隐式 enabled=True
        if isinstance(proxies_cfg, dict):
            proxies_cfg = [proxies_cfg]
        cfg = self.generate_config(proxies_cfg, active_node, nodes)
        self.write_config(cfg)
        self.stop(wait=True)
        enabled_list = [p for p in (proxies_cfg or []) if p.get("enabled")]
        if not enabled_list:
            return True, "已停止（无启用的代理配置）"
        return self.start()

    def _wait_port_ready(self, listen, port, timeout=5.0):
        """轮询 TCP 端口监听以判断核心就绪。"""
        host = listen if listen not in ("0.0.0.0", "::") else "127.0.0.1"
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                import socket as _sock
                s = _sock.create_connection((host, int(port)), timeout=0.5)
                s.close()
                return True
            except OSError:
                time.sleep(0.15)
        return False

    def _enabled_listen_port(self):
        """从配置文件推断首个 inbound 的 listen/port 用于就绪探测。"""
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for ib in (cfg.get("inbounds") or []):
                if ib.get("type") == "mixed":
                    return ib.get("listen") or "127.0.0.1", int(ib.get("listen_port") or 0)
        except (OSError, ValueError):
            pass
        return None

    def start(self):
        with self._lock:
            binary = self.binary
            if not binary:
                self._last_error = "未找到 sing-box 可执行文件"
                return False, self._last_error
            if self.is_running():
                return True, "已运行"
            if not os.path.isfile(self.config_file):
                return False, "配置尚未生成，请先在代理页面保存并应用配置"
            # 父进程负责打开日志 fd 给子进程使用；Popen 之后必须立即在父进程关闭
            try:
                log_f = open(self.core_log, "a", encoding="utf-8")
            except OSError as e:
                self._last_error = "无法打开核心日志文件: %s" % e
                self.log.error(self._last_error)
                return False, self._last_error
            try:
                kwargs = {}
                if sys.platform == "win32":
                    kwargs["creationflags"] = CREATE_NO_WINDOW
                self._proc = subprocess.Popen(
                    [binary, "run", "-c", self.config_file],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    **kwargs
                )
                self._write_pid(self._proc.pid)
            except OSError as e:
                self._last_error = "启动 sing-box 失败: %s" % e
                self.log.error(self._last_error)
                log_f.close()
                return False, self._last_error
            finally:
                # 关键：父进程必须关闭 log_f（子进程已 dup），否则反复 restart 泄漏 fd
                log_f.close()
            # 改为「先短暂判断立即退出，再轮询端口就绪」，替代原 sleep(1.2)
            time.sleep(0.3)
            if self._proc.poll() is not None:
                self._last_error = "sing-box 启动后立即退出（rc=%s），请查看核心日志" % self._proc.returncode
                self._clear_pid()
                self.log.error(self._last_error)
                return False, self._last_error
            # 轮询端口 listen 状态判断核心就绪
            lp = self._enabled_listen_port()
            if lp:
                listen, port = lp
                if port and not self._wait_port_ready(listen, port, timeout=5.0):
                    # 端口未就绪：再确认进程是否还活着
                    if self._proc.poll() is None:
                        self.log.warn("sing-box 已启动但端口尚未就绪 (pid=%d)" % self._proc.pid)
                        return True, "已启动 (pid=%d，端口就绪中)" % self._proc.pid
                    self._last_error = "sing-box 启动后异常退出，请查看核心日志"
                    self._clear_pid()
                    self.log.error(self._last_error)
                    return False, self._last_error
            self.log.info("sing-box 已启动 (pid=%d)" % self._proc.pid)
            return True, "已启动 (pid=%d)" % self._proc.pid

    def stop(self, wait=True):
        with self._lock:
            pid = self._read_pid()
            proc = self._proc
            if proc is not None and proc.poll() is None:
                pid = proc.pid
            if not pid:
                self._proc = None
                self._clear_pid()
                return True
            # 优先用 Popen.wait 等待退出（避免 os.kill + 手动 sleep 的竞态）
            if proc is not None and proc.poll() is None:
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True, timeout=10
                        )
                    else:
                        try:
                            proc.terminate()
                        except OSError:
                            pass
                except (OSError, subprocess.SubprocessError) as e:
                    self.log.warn("停止 sing-box 异常: %s" % e)
                if wait:
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            proc.kill()
                            proc.wait(timeout=2)
                        except (OSError, subprocess.TimeoutExpired):
                            self.log.warn("sing-box 未能正常退出")
            else:
                # 进程非由本对象管理（如重启服务），用 PID 信号
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True, timeout=10
                        )
                    else:
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except OSError:
                            try:
                                os.kill(pid, signal.SIGKILL)
                            except OSError as e:
                                self.log.warn("停止 sing-box 异常: %s" % e)
                        if wait:
                            # 轮询确认退出（最多 ~3s）
                            end = time.monotonic() + 3
                            while time.monotonic() < end:
                                if not self._pid_alive(pid):
                                    break
                                time.sleep(0.1)
                except (OSError, subprocess.SubprocessError) as e:
                    self.log.warn("停止 sing-box 异常: %s" % e)
            self._proc = None
            self._clear_pid()
            return True

    def restart(self):
        self.stop(wait=True)
        return self.start()

    def status(self):
        running = self.is_running()
        return {
            "running": running,
            "pid": self._read_pid() if running else None,
            "version": self.version(),
            "binary": self.binary or None,
            "last_error": self._last_error,
            "config_file": self.config_file if os.path.isfile(self.config_file) else None,
        }