"""The directory a director agent works in: a Hypit project plus the Skill, a guard and the task's material."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..hypit.cli import HypitCli, HypitError
from .models import ModelPlan
from .prompts import ASSET_PATHS, REFERENCE_PATH
from .services import PROVIDERS_DIR, TEMPLATE_DIR
from .whisperx import PLACEHOLDER, write_start_script

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PACKAGE_DIR = Path(__file__).resolve().parent
GUARD_SOURCE = PACKAGE_DIR / "guard" / "hypit_guard.mjs"
BASE_DEPENDENCIES = {"@fontsource-variable/montserrat": "^5.3.0"}


def find_skill_dir(configured: str = "") -> Path:
    """The Hypit Skill: a configured folder, the bundled copy, or the repository checkout."""
    candidates = [Path(configured)] if configured else []
    candidates += [PACKAGE_DIR.parents[1] / "skills" / "hypit", PACKAGE_DIR.parents[2] / "skills" / "hypit"]
    for path in candidates:
        if (path / "SKILL.md").is_file():
            return path
    raise HypitError("找不到 Hypit Skill(skills/hypit)。请在设置里指定它的位置。")


@dataclass
class Workspace:
    path: Path
    reference: Path
    images: dict[str, str]   # brief key -> project-relative path of the copied image

    @property
    def bin_dir(self) -> Path:
        return self.path / "bin"


def _npm_install(project: Path, use_env_proxy: bool) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise HypitError("找不到 npm,无法安装项目依赖;请先安装 Node.js。")
    env = dict(os.environ)
    if use_env_proxy:
        env["NODE_USE_ENV_PROXY"] = "1"
    # --install-links copies local packages instead of linking them, so they resolve the project's @hypit packages
    done = subprocess.run([npm, "install", "--install-links", "--no-audit", "--no-fund"], cwd=str(project), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=900, creationflags=_NO_WINDOW)
    if done.returncode != 0:
        raise HypitError("安装项目依赖失败:" + (done.stderr or done.stdout).strip()[-400:])


def _write_shims(bin_dir: Path, node: str) -> None:
    """`hypit` for the agent's shell: a thin wrapper that runs the guard under Node."""
    bin_dir.mkdir(exist_ok=True)
    guard = bin_dir / "hypit_guard.mjs"
    shutil.copy2(GUARD_SOURCE, guard)
    (bin_dir / "hypit").write_text(f'#!/usr/bin/env bash\nexec "{Path(node).as_posix()}" "{guard.as_posix()}" "$@"\n',
                                   encoding="utf-8", newline="\n")
    (bin_dir / "hypit.cmd").write_text(f'@"{node}" "{guard}" %*\r\n', encoding="utf-8")


def _copy_assets(project: Path, brief: dict) -> dict[str, str]:
    copied = {}
    for key, stem in ASSET_PATHS.items():
        source = brief.get(key) or ""
        if not source:
            continue
        src = Path(source)
        if not src.is_file():
            raise HypitError(f"替换用的图片不存在:{source}")
        target = project / f"{stem}{src.suffix.lower() or '.png'}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied[key] = target.relative_to(project).as_posix()
    return copied


def _fetch_reference(cli: HypitCli, project: Path, brief: dict) -> Path:
    target = project / REFERENCE_PATH
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if brief.get("source_type") == "file":
        source = Path(brief["url"])
        if not source.is_file():
            raise HypitError(f"参考视频文件不存在:{source}")
        shutil.copy2(source, target)
    else:
        cli.download(project, brief["url"], REFERENCE_PATH)
    return target


def prepare_workspace(cli: HypitCli, data_dir: Path, project_id: int, brief: dict, models: ModelPlan,
                      skill_dir: Path, node: str, template: Path = TEMPLATE_DIR,
                      whisperx_home: Optional[Path] = None) -> Workspace:
    """Create or refresh the project for a task. Safe to call again on a retry."""
    project = Path(data_dir).resolve() / "projects" / f"task-{project_id}"  # absolute: the shims embed these paths
    project.mkdir(parents=True, exist_ok=True)

    manifest_path = project / "package.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"name": f"task-{project_id}", "version": "0.0.0", "private": True, "type": "module",
                    "hypit": {"project": True}, "dependencies": {}}
    service = models.service
    wanted = {**BASE_DEPENDENCIES, **service.dependencies, models.font_package: "^5.3.0"}
    for folder in service.local_packages:
        package = json.loads((PROVIDERS_DIR / folder / "package.json").read_text(encoding="utf-8"))
        wanted[package["name"]] = f"file:{(PROVIDERS_DIR / folder).resolve().as_posix()}"
    missing = {name: version for name, version in wanted.items() if name not in manifest.setdefault("dependencies", {})}
    manifest["dependencies"].update(missing)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not (project / "hypit.runtime.json").is_file():
        profile = (template / service.runtime_template).read_text(encoding="utf-8")
        if whisperx_home is not None:
            start = write_start_script(whisperx_home)
            profile = profile.replace(PLACEHOLDER, json.dumps(str(start))[1:-1])  # a JSON-escaped Windows path
        (project / "hypit.runtime.json").write_text(profile, encoding="utf-8")
    if missing or not (project / "node_modules").is_dir():
        _npm_install(project, cli.use_env_proxy)
    if not (project / ".hypit" / "runtime").is_file():
        cli.select_runtime(project)

    skill = project / ".claude" / "skills" / "hypit"
    if not skill.is_dir():
        shutil.copytree(skill_dir, skill)
    _write_shims(project / "bin", node)
    images = _copy_assets(project, brief)
    reference = _fetch_reference(cli, project, brief)
    return Workspace(project, reference, images)
