"""Choose the agent backend from user settings."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from ..credentials import ARK_KEY, KeyStore, key_name, stored_or_env
from ..hypit.cli import HypitCli
from .base import AgentBackend
from .agent_backend import AgentConfig, HypitAgentBackend
from .hypit_backend import TEMPLATE_DEFAULT, HypitCliBackend
from .llm import llm_provider
from .replay import replay_backend_factory
from .services import service_by_id

DEFAULT_LAUNCHER = r"D:\Dev\hypit-runtime\node_modules\@hypit\hypit\bin\hypit.mjs"


def hypit_backend_from(settings, data_dir: Path) -> HypitCliBackend:
    node = settings.get("node_path") or shutil.which("node") or "node"
    cli = HypitCli(Path(settings.get("hypit_launcher") or DEFAULT_LAUNCHER), node=node,
                   use_env_proxy=bool(settings.get("use_env_proxy")))
    project = settings.get("hypit_project_dir")
    return HypitCliBackend(cli, data_dir, template=Path(settings.get("hypit_template") or TEMPLATE_DEFAULT),
                           project_dir=Path(project) if project else None,
                           run_source=settings.get("hypit_run_source") or "reference.svrun")


def agent_backend_from(settings, data_dir: Path, store: Optional[KeyStore] = None) -> HypitAgentBackend:
    node = settings.get("node_path") or shutil.which("node") or "node"
    launcher = settings.get("hypit_launcher") or DEFAULT_LAUNCHER
    use_proxy = bool(settings.get("use_env_proxy"))
    service = service_by_id(settings.get("generation_service"))     # unknown (planned) ids fall back; the backend refuses them
    director = llm_provider(settings.get("llm_provider"))
    worker_env = {service.credential_env: stored_or_env(store, ARK_KEY, service.credential_env)} if service.credential_env else {}
    cli = HypitCli(Path(launcher), node=node, use_env_proxy=use_proxy, extra_env=worker_env)
    config = AgentConfig(launcher=launcher, node=node, use_env_proxy=use_proxy,
                         llm_base_url=settings.get("llm_base_url"), llm_model=settings.get("llm_model"),
                         llm_key_env=settings.get("llm_key_env"), skill_dir=settings.get("hypit_skill_dir"),
                         llm_key=stored_or_env(store, key_name(director.id if director.id != "custom" else "deepseek"),
                                               director.env_var or settings.get("llm_key_env")),
                         llm_auth=director.auth, llm_max_context=director.max_context,
                         llm_unavailable=director.note if not director.runnable else "",
                         generation_service=settings.get("generation_service") or "hypihub",
                         whisperx_home=settings.get("whisperx_home") or "")
    return HypitAgentBackend(cli, data_dir, config)


def make_backend_factory(data_dir: Path, store: Optional[KeyStore] = None) -> Callable[[object], AgentBackend]:
    def factory(settings) -> AgentBackend:
        if settings.get("backend") == "agent":
            return agent_backend_from(settings, data_dir, store)
        if settings.get("backend") == "hypit":
            return hypit_backend_from(settings, data_dir)
        return replay_backend_factory(settings)
    return factory
