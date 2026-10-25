"""Thin wrapper over the Hypit command line. Every call runs in a video project directory."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class HypitError(Exception):
    """A Hypit command failed; the message is Hypit's own explanation."""


class HypitCli:
    def __init__(self, launcher: Path, node: str = "node", use_env_proxy: bool = True,
                 runner: Optional[Callable] = None):
        self.launcher = Path(launcher)
        self.node = node
        self.use_env_proxy = use_env_proxy
        self._run = runner or subprocess.run

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.use_env_proxy:
            # Node's HTTP client ignores HTTP(S)_PROXY unless asked; downloads stall behind a proxy otherwise.
            env["NODE_USE_ENV_PROXY"] = "1"
        return env

    def call(self, args: list[str], project: Path, timeout: float = 120) -> str:
        cmd = [self.node, str(self.launcher), *args]
        try:
            done = self._run(cmd, cwd=str(project), env=self._env(), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
        except FileNotFoundError as exc:
            raise HypitError(f"找不到 Node.js 或 Hypit:{exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise HypitError(f"hypit {' '.join(args[:2])} 超过 {timeout:.0f} 秒没有响应") from exc
        if done.returncode != 0:
            raise HypitError((done.stdout + "\n" + done.stderr).strip() or f"hypit 退出码 {done.returncode}")
        return done.stdout

    def json(self, args: list[str], project: Path, timeout: float = 120) -> dict:
        text = self.call([*args, "--json"], project, timeout)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise HypitError(f"hypit 输出不是 JSON:{text[:200]}") from exc

    # --- the commands the app needs ---------------------------------------------------------
    def version(self, project: Path) -> str:
        return self.call(["version"], project, 60).splitlines()[0].strip()

    def select_runtime(self, project: Path, profile: str = "./hypit.runtime.json") -> None:
        self.call(["runtime", "use", profile], project, 60)

    def runtime_up(self, project: Path) -> None:
        self.call(["runtime", "up"], project, 600)

    def download(self, project: Path, url: str, destination: str) -> None:
        """Fetch a network video into the project (needs `hypit download prepare` to have been run once)."""
        try:
            self.call(["download", url, "--to", destination], project, 900)
        except HypitError as exc:
            if "prepare" in str(exc).lower():
                raise HypitError("下载网络视频需要先在终端运行一次 `hypit download prepare`(需要先安装 uv)。"
                                 "或者先把视频下载到本地,在任务里选“本地文件”。") from exc
            raise

    def check(self, project: Path, run_source: str) -> None:
        self.call(["check", run_source], project, 300)

    def outputs(self, project: Path, build_id: str) -> list[dict]:
        """Public Outputs of a finished (or failed) Build: name, type, kind, target, mediaType, size."""
        data = self.json(["inspect", build_id, "--verbose", "--limit", "2000"], project, 180)
        return data["build"].get("outputs", [])

    def pricing(self, project: Path, run_source: str) -> dict:
        return self.json(["pricing", run_source], project, 300)

    def build(self, project: Path, run_source: str, title: str) -> str:
        data = self.json(["build", run_source, "--title", title], project, 180)
        return data["build"]["id"]

    def status(self, project: Path, build_id: str) -> dict:
        return self.json(["status", build_id], project, 90)["build"]

    def cancel(self, project: Path, build_id: str) -> None:
        self.call(["cancel", build_id], project, 90)

    def export(self, project: Path, build_id: str, output: str, destination: Path) -> None:
        self.call(["get", build_id, "--output", output, "--to", str(destination)], project, 300)
