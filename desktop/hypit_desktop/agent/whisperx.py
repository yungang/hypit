"""The local WhisperX service (speech alignment) is installed once per machine by the app and shared by every task.

Hypit can also manage that installation itself, but it reconciles the Python environment from each project's own
package path, which rebuilds the service for every task and fails while the service runs. So the app owns the
installation and only hands Hypit a start command (`serviceCommand`); Hypit then just probes /health.

The folder is relocatable: the start script runs the interpreter that ships inside it and adds the bundled packages
to its path, so nothing depends on where the folder was built (a venv's own launchers record absolute paths)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from ..hypit.cli import HypitError
from .services import PACKAGE_DIR

START_SCRIPT = "start-whisperx.cmd"
PLACEHOLDER = "{{WHISPERX_START}}"
DEFAULT_LANGUAGES = ("zh", "en")
SITE_PACKAGES = Path(".venv") / "Lib" / "site-packages"
SERVICE_PACKAGE = SITE_PACKAGES / "hypit_whisperx_service"
SERVICE_EXE = Path(".venv") / "Scripts" / "hypit-whisperx-service.exe"   # only used when no interpreter is bundled
REPARSE_POINT = 0x400


def _is_link(path: Path) -> bool:
    """A junction or symlink (uv leaves `cpython-3.13-...` pointing at the versioned folder by absolute path)."""
    try:
        return bool(os.lstat(path).st_file_attributes & REPARSE_POINT)
    except (OSError, AttributeError):
        return path.is_symlink()


def bundled_python(home: Path) -> Optional[Path]:
    """The interpreter shipped inside the bundle, relative to it, or None for a layout without one."""
    root = home / "python"
    if root.is_dir():
        for folder in sorted(root.glob("cpython-*")):
            if (folder / "python.exe").is_file() and not _is_link(folder):
                return (folder / "python.exe").relative_to(home)
    return None


def app_folders() -> list[Path]:
    """Where `services/whisperx` is looked for next to the program: beside the exe, then inside its data folder."""
    folders = [Path(sys.executable).parent / "services" / "whisperx"] if getattr(sys, "frozen", False) else []
    return folders + [PACKAGE_DIR.parents[1] / "services" / "whisperx", PACKAGE_DIR.parents[2] / "services" / "whisperx"]


def find_whisperx_home(configured: str = "") -> Path:
    """The folder holding `.venv` and `nltk_data`: a configured one, or `services/whisperx` next to the app."""
    candidates = ([Path(configured)] if configured else []) + app_folders()
    for path in candidates:
        if (path / SERVICE_PACKAGE).is_dir():
            return path.resolve()
    raise HypitError("本地语音对齐服务还没有安装。请把 whisperx 文件夹放到程序目录下的 services 文件夹里,"
                     "或在设置里指定它的位置(包含 .venv 的文件夹)。")


def write_start_script(home: Path, languages: tuple[str, ...] = DEFAULT_LANGUAGES) -> Path:
    """The command Hypit runs when the service is down. Its settings must match the profile's expected* values.
    A bundled `models` folder (huggingface/ and torch/ inside) is used for every model when it exists."""
    script = home / START_SCRIPT
    lines = [
        "@echo off",
        "set HYPIT_WHISPERX_PORT=8765",
        "set HYPIT_WHISPERX_MODEL=small",
        "set HYPIT_WHISPERX_DEVICE=cpu",
        "set HYPIT_WHISPERX_COMPUTE=int8",
        "set HYPIT_WHISPERX_BATCH_SIZE=8",
        'set "HYPIT_WHISPERX_NLTK_DATA=%~dp0nltk_data"',
    ]
    if (home / "models").is_dir():
        lines.append('set "HYPIT_WHISPERX_MODEL_CACHE=%~dp0models"')
    lines.append(f'set "HYPIT_WHISPERX_ALIGNMENT_LANGUAGES={" ".join(languages)}"')
    python = bundled_python(home)
    if python is None:
        lines.append(f'"%~dp0{SERVICE_EXE}"')
    else:
        lines += [
            "set PYTHONNOUSERSITE=1",
            f'set "HYPIT_SITE_PACKAGES=%~dp0{SITE_PACKAGES}"',
            f'"%~dp0{python}" -c "import os, site, sys; site.addsitedir(os.environ[\'HYPIT_SITE_PACKAGES\']); '
            f"from hypit_whisperx_service.__main__ import main; sys.exit(main())\"",
        ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="ascii", newline="")
    return script


if __name__ == "__main__":   # python -m hypit_desktop.agent.whisperx <home>: used by deploy/build_whisperx_bundle.ps1
    print(write_start_script(Path(sys.argv[1])))
