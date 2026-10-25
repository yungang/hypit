"""Choose the agent backend from user settings."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from ..hypit.cli import HypitCli
from .base import AgentBackend
from .agent_backend import AgentConfig, HypitAgentBackend
from .hypit_backend import TEMPLATE_DEFAULT, HypitCliBackend
from .replay import replay_backend_factory

DEFAULT_LAUNCHER = r"D:\Dev\hypit-runtime\node_modules\@hypit\hypit\bin\hypit.mjs"


def hypit_backend_from(settings, data_dir: Path) -> HypitCliBackend:
    node = settings.get("node_path") or shutil.which("node") or "node"
    cli = HypitCli(Path(settings.get("hypit_launcher") or DEFAULT_LAUNCHER), node=node,
                   use_env_proxy=bool(settings.get("use_env_proxy")))
    project = settings.get("hypit_project_dir")
    return HypitCliBackend(cli, data_dir, template=Path(settings.get("hypit_template") or TEMPLATE_DEFAULT),
                           project_dir=Path(project) if project else None,
                           run_source=settings.get("hypit_run_source") or "reference.svrun")


def agent_backend_from(settings, data_dir: Path) -> HypitAgentBackend:
    node = settings.get("node_path") or shutil.which("node") or "node"
    launcher = settings.get("hypit_launcher") or DEFAULT_LAUNCHER
    use_proxy = bool(settings.get("use_env_proxy"))
    cli = HypitCli(Path(launcher), node=node, use_env_proxy=use_proxy)
    config = AgentConfig(launcher=launcher, node=node, use_env_proxy=use_proxy,
                         llm_base_url=settings.get("llm_base_url"), llm_model=settings.get("llm_model"),
                         llm_key_env=settings.get("llm_key_env"), skill_dir=settings.get("hypit_skill_dir"))
    return HypitAgentBackend(cli, data_dir, config)


def make_backend_factory(data_dir: Path) -> Callable[[object], AgentBackend]:
    def factory(settings) -> AgentBackend:
        if settings.get("backend") == "agent":
            return agent_backend_from(settings, data_dir)
        if settings.get("backend") == "hypit":
            return hypit_backend_from(settings, data_dir)
        return replay_backend_factory(settings)
    return factory
