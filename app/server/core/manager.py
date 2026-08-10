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


class CoreManager(object):
    def __init__(self, work_dir, core_binary=None, logger=None):
        self.work_dir = util.ensure_dir(work_dir)
        self.log = logger or get_logger(tag="core")
        self.core_binary = core_binary or ""
        self.pid_file = os.path.join(self.work_dir, "core.pid")
        self.config_file = os.path.join(self.work_dir, "config.json")
        self.core_log = os.path.join(self.work_dir, "core.log")
        self._proc = None
        self._lock = threading.Lock()
        self._last_error = None
        self._version = None

    def find_binary(self, candidates=None):
        cands = candidates or [self.core_binary]
        for c in cands:
            if not c:
                continue
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        for name in ("sing-box", "sing-box.exe"):
            for base in os.environ.get("PATH", "").split(os.pathsep):
                if not base:
                    continue
                p = os.path.join(base, name)
                if os.path.isfile(p):
                    return p
        return None

    def set_binary(self, path):
        self.core_binary = path or ""

    @property
    def binary(self):
        return self.find_binary() or ""

    def is_running(self):
        pid = self._read_pid()
        if pid and self._pid_alive(pid):
            return True
        self._clear_pid()
        self._proc = None
        return False

    def _read_pid(self):
        try:
            with open(self.pid_file, "r") as f:
                return int(f.read().strip() or 0)
        except Exception:
            return 0

    def _write_pid(self, pid):
        try:
            with open(self.pid_file, "w") as f:
                f.write(str(pid))
        except Exception:
            pass

    def _clear_pid(self):
        try:
            if os.path.isfile(self.pid_file):
                os.remove(self.pid_file)
        except Exception:
            pass

    def _pid_alive(self, pid):
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
                return exit_code.value == 259
            except Exception:
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
        except Exception:
            return None

    def generate_config(self, proxies_cfg, active_node, nodes=None):
        return config_gen.build_config(proxies_cfg, active_node, nodes, log_file=self.core_log)

    def write_config(self, cfg):
        config_gen.config_to_json(cfg)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return self.config_file

    def apply(self, proxies_cfg, active_node, nodes=None):
        binary = self.binary
        if not binary:
            self._last_error = "未找到 sing-box 可执行文件，请在设置中配置核心路径或重新安装"
            return False, self._last_error
        cfg = self.generate_config(proxies_cfg, active_node, nodes)
        self.write_config(cfg)
        self.stop(wait=True)
        if isinstance(proxies_cfg, dict):
            proxies_cfg = [proxies_cfg]
        enabled_list = [p for p in (proxies_cfg or []) if p.get("enabled")]
        if not enabled_list:
            return True, "已停止（无启用的代理配置）"
        return self.start()

    def start(self):
        binary = self.binary
        if not binary:
            self._last_error = "未找到 sing-box 可执行文件"
            return False, self._last_error
        if self.is_running():
            return True, "已运行"
        if not os.path.isfile(self.config_file):
            return False, "配置尚未生成，请先在代理页面保存并应用配置"
        log_f = open(self.core_log, "a", encoding="utf-8")
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
        except Exception as e:
            self._last_error = "启动 sing-box 失败: %s" % e
            self.log.error(self._last_error)
            return False, self._last_error
        time.sleep(1.2)
        if self._proc.poll() is not None:
            self._last_error = "sing-box 启动后立即退出（rc=%s），请查看核心日志" % self._proc.returncode
            self._clear_pid()
            self.log.error(self._last_error)
            return False, self._last_error
        self.log.info("sing-box 已启动 (pid=%d)" % self._proc.pid)
        return True, "已启动 (pid=%d)" % self._proc.pid

    def stop(self, wait=True):
        pid = self._read_pid()
        if self._proc and self._proc.poll() is None:
            pid = self._proc.pid
        if not pid:
            return True
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=10
                )
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    os.kill(pid, signal.SIGKILL)
        except Exception as e:
            self.log.warn("停止 sing-box 异常: %s" % e)
        if wait:
            time.sleep(0.8)
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
