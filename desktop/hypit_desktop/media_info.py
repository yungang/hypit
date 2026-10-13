"""Best-effort ffprobe / ffmpeg helpers. Everything degrades to None when ffmpeg is absent."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def probe(path: str) -> dict | None:
    exe = shutil.which("ffprobe")
    if not exe or not Path(path).is_file():
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW)
        data = json.loads(out.stdout)
        stream = data["streams"][0]
        return {"width": int(stream["width"]), "height": int(stream["height"]),
                "duration": float(data["format"]["duration"])}
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return None


def describe(info: dict) -> str:
    return f"时长 {info['duration']:.1f} 秒 · {info['width']}x{info['height']}"


def make_thumbnail(video: str, out_png: Path) -> bool:
    exe = shutil.which("ffmpeg")
    if not exe or not Path(video).is_file():
        return False
    out_png.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([exe, "-y", "-v", "error", "-ss", "1", "-i", video, "-frames:v", "1",
                        "-vf", "scale=240:-2", str(out_png)],
                       capture_output=True, timeout=30, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return out_png.is_file()
