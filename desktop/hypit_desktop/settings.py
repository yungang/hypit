"""Small JSON-backed user settings."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {"export_dir": "", "scenario": "normal", "replay_speed": 1.0,
            "max_concurrent": 2, "featured_seeded": False,
            # real backend: "replay" plays recorded events, "hypit" runs the Hypit CLI (spends HypiHub credits)
            "backend": "replay", "hypit_launcher": "", "node_path": "", "use_env_proxy": True,
            "hypit_project_dir": "", "hypit_template": "", "hypit_run_source": "",
            # AI director (backend "agent"): an Anthropic-compatible endpoint; the key is read from this env var
            "llm_base_url": "https://api.deepseek.com/anthropic", "llm_model": "deepseek-flash",
            "llm_key_env": "DEEPSEEK_API_KEY", "hypit_skill_dir": ""}


class Settings:
    def __init__(self, path: Path):
        self._path = path
        self._values = dict(DEFAULTS)
        try:
            self._values.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def get(self, key: str):
        return self._values[key]

    def set(self, key: str, value) -> None:
        self._values[key] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._values, ensure_ascii=False, indent=2), encoding="utf-8")
