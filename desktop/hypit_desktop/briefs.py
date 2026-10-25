"""Clone parameters (the 'brief') shared by the form, the queue and the agent."""
from __future__ import annotations

from pathlib import Path

MODELS = [
    "Seedance 2.5", "Seedance 2.5 Draft", "Seedance 2.0 Fast VIP", "Seedance 2.0 VIP",
    "Seedance 2.0 Mini 体验版", "Seedance 2.0 Mini", "Wan 3.0", "HappyHorse 1.1", "Seedance 1.0 Fast",
]
DEFAULT_MODEL = MODELS[0]
ASPECTS = ["源比例", "16:9", "9:16", "4:3"]
RESOLUTIONS = ["480p", "720p", "1080p", "2K", "4K"]
MARKETS = ["中国大陆", "美国", "英国", "日本", "韩国", "东南亚", "中东", "拉美", "欧洲"]
LANGUAGES = ["中文", "English", "日本語", "한국어", "Español", "Français", "Deutsch", "Bahasa Indonesia", "العربية"]
DURATION_PRESETS = [5, 10, 15, 20, 30, 60]

# Optional replacement images; an empty value keeps that part of the source video.
IMAGE_KEYS = (("role_image", "角色"), ("product_image", "商品"), ("background_image", "背景"))

DEFAULTS = {
    "mode": "simple",          # simple | pro
    "source_type": "url",      # url | file
    "url": "",                 # link, or local path when source_type == file
    "source_info": "",
    "topic": "", "scene": "",
    "product": "",             # legacy text field from earlier versions; the form no longer sets it
    "role_image": "", "product_image": "", "background_image": "",
    "market": MARKETS[0], "language": LANGUAGES[0],
    "model": DEFAULT_MODEL, "aspect": ASPECTS[0], "resolution": "720p",
    "duration": "15 秒",
    "extra_prompt": "", "preview_first": False,
}
# Parameters a template remembers (everything except the source and the per-task theme/images).
TEMPLATE_KEYS = ("scene", "market", "language", "model", "aspect", "resolution",
                 "duration", "extra_prompt", "preview_first")


def normalize(brief: dict) -> dict:
    """Fill keys missing from briefs saved by earlier versions."""
    return {**DEFAULTS, **brief}


def title_of(brief: dict) -> str:
    brief = normalize(brief)
    title = brief["topic"] or "未命名"
    return f"{title} · {brief['product']}" if brief["product"] else title


def replaced_parts(brief: dict) -> list[str]:
    b = normalize(brief)
    return [label for key, label in IMAGE_KEYS if b[key]]


def summary_of(brief: dict) -> str:
    b = normalize(brief)
    source = b["url"] if b["source_type"] == "url" else "本地文件:" + b["url"]
    parts = [source, f"{b['market']}/{b['language']}", b["model"], b["aspect"], b["resolution"], b["duration"]]
    replaced = replaced_parts(b)
    parts.append("替换:" + "、".join(replaced) if replaced else "沿用原视频画面")
    if b["mode"] == "pro":
        parts.append("专业模式")
    return " · ".join(p for p in parts if p)


def image_problems(brief: dict) -> list[str]:
    """Names of replacement images whose file is missing."""
    b = normalize(brief)
    return [label for key, label in IMAGE_KEYS if b[key] and not Path(b[key]).is_file()]
