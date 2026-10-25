"""Create a video project directory for one task from a template and make it ready to build."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .cli import HypitCli, HypitError

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_COPY_IGNORE = shutil.ignore_patterns("node_modules", ".hypit", "exported", "__pycache__")


def _install_dependencies(project: Path, use_env_proxy: bool) -> None:
    manifest = json.loads((project / "package.json").read_text(encoding="utf-8"))
    if not manifest.get("dependencies"):
        return
    npm = shutil.which("npm")
    if npm is None:
        raise HypitError("找不到 npm,无法安装项目依赖;请先安装 Node.js。")
    env = dict(os.environ)
    if use_env_proxy:
        env["NODE_USE_ENV_PROXY"] = "1"
    done = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=str(project), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=900, creationflags=_NO_WINDOW)
    if done.returncode != 0:
        raise HypitError("安装项目依赖失败:" + (done.stderr or done.stdout).strip()[-400:])


def prepare_project(cli: HypitCli, template: Path, destination: Path) -> Path:
    """Copy the template (once) and install its dependencies, then select its Runtime Profile."""
    if not (destination / "package.json").is_file():
        if not (template / "package.json").is_file():
            raise HypitError(f"项目模板不存在:{template}")
        shutil.copytree(template, destination, ignore=_COPY_IGNORE, dirs_exist_ok=True)
    if not (destination / "node_modules").is_dir():
        _install_dependencies(destination, cli.use_env_proxy)
    if not (destination / ".hypit" / "runtime").is_file():
        cli.select_runtime(destination)
    return destination
