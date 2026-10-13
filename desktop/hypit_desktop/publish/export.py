"""Export a ready-to-post folder: the video, copy text per platform, and a checklist.
Nothing is sent anywhere; the person uploads it on each platform's own page."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .base import PublishMeta
from .platforms import BY_ID, PLATFORMS


def _safe_name(text: str) -> str:
    cleaned = re.sub(r'[\/:*?"<>|\s]+', "_", text).strip("._")
    return cleaned[:40] or "video"


def _copy_text(meta: PublishMeta) -> str:
    tags = " ".join("#" + t.lstrip("#") for t in meta.tags)
    parts = [meta.title]
    if meta.description:
        parts.append(meta.description)
    if tags:
        parts.append(tags)
    return "\n\n".join(parts) + "\n"


def export_package(video_path: str, meta: PublishMeta, platform_ids: list[str],
                   out_dir: Path) -> Path:
    """Create <out_dir>/<title>_<timestamp>/ and return it. Empty platform_ids means all."""
    platforms = [BY_ID[p] for p in platform_ids] if platform_ids else PLATFORMS
    folder = Path(out_dir) / f"{_safe_name(meta.title)}_{time.strftime('%Y%m%d_%H%M%S')}"
    folder.mkdir(parents=True)

    video = Path(video_path)
    has_video = video.is_file()
    if has_video:
        shutil.copy2(video, folder / f"video{video.suffix}")

    text = _copy_text(meta)
    checklist = ["发布清单", "=" * 8, ""]
    if not has_video:
        checklist += ["注意:未找到视频文件,请手动补充。", ""]
    for p in platforms:
        (folder / f"文案_{p.name}.txt").write_text(text, encoding="utf-8")
        checklist.append(f"[ ] {p.name}  {p.upload_url or '(无上传页地址,请自行查找)'}")
    checklist += ["", "文案可直接复制;各平台的话题、字数规则请以上传页提示为准。"]
    (folder / "发布清单.txt").write_text("\n".join(checklist) + "\n", encoding="utf-8")
    return folder
