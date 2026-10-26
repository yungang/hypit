"""The local WhisperX service (speech alignment) is installed once per machine by the app and shared by every task.

Hypit can also manage that installation itself, but it reconciles the Python environment from each project's own
package path, which rebuilds the service for every task and fails while the service runs. So the app owns the
installation and only hands Hypit a start command (`serviceCommand`); Hypit then just probes /health."""
from __future__ import annotations

import sys
from pathlib import Path

from ..hypit.cli import HypitError
from .services import PACKAGE_DIR

START_SCRIPT = "start-whisperx.cmd"
PLACEHOLDER = "{{WHISPERX_START}}"
DEFAULT_LANGUAGES = ("zh", "en")
SERVICE_EXE = Path(".venv") / "Scripts" / "hypit-whisperx-service.exe"
STANDARD_HOME = Path("C:/HypitDesktop/services/whisperx")   # where deploy/build_whisperx_bundle.ps1 builds by default


def find_whisperx_home(configured: str = "") -> Path:
    """The folder holding `.venv` and `nltk_data`: a configured one, or `services/whisperx` next to the app."""
    candidates = [Path(configured)] if configured else []
    candidates += [STANDARD_HOME, PACKAGE_DIR.parents[1] / "services" / "whisperx", PACKAGE_DIR.parents[2] / "services" / "whisperx"]
    for path in candidates:
        if (path / SERVICE_EXE).is_file():
            return path.resolve()
    raise HypitError("本地语音对齐服务还没有安装。请在设置里指定它的位置(包含 .venv 的文件夹),或重新安装应用。")


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
    lines += [f'set "HYPIT_WHISPERX_ALIGNMENT_LANGUAGES={" ".join(languages)}"', f'"%~dp0{SERVICE_EXE}"']
    script.write_text("\r\n".join(lines) + "\r\n", encoding="ascii", newline="")
    return script


if __name__ == "__main__":   # python -m hypit_desktop.agent.whisperx <home>: used by deploy/build_whisperx_bundle.ps1
    print(write_start_script(Path(sys.argv[1])))
