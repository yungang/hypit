"""Clone parameters (the 'brief') shared by the form, the queue and the agent."""
from __future__ import annotations

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

DEFAULTS = {
    "mode": "simple",          # simple | pro
    "source_type": "url",      # url | file
    "url": "",                 # link, or local path when source_type == file
    "source_info": "",
    "topic": "", "scene": "", "product": "",
    "market": MARKETS[0], "language": LANGUAGES[0],
    "model": DEFAULT_MODEL, "aspect": ASPECTS[0], "resolution": "720p",
    "duration": "15 秒",
    "extra_prompt": "", "preview_first": False,
}
# Parameters a template remembers (everything except the source and the per-task topic/product).
TEMPLATE_KEYS = ("scene", "market", "language", "model", "aspect", "resolution",
                 "duration", "extra_prompt", "preview_first")


def normalize(brief: dict) -> dict:
    """Fill keys missing from briefs saved by earlier versions."""
    return {**DEFAULTS, **brief}


def title_of(brief: dict) -> str:
    brief = normalize(brief)
    title = brief["topic"] or "未命名"
    return f"{title} · {brief['product']}" if brief["product"] else title


def summary_of(brief: dict) -> str:
    b = normalize(brief)
    source = b["url"] if b["source_type"] == "url" else "本地文件:" + b["url"]
    parts = [source, f"{b['market']}/{b['language']}", b["model"], b["aspect"], b["resolution"], b["duration"]]
    if b["mode"] == "pro":
        parts.append("专业模式")
    return " · ".join(p for p in parts if p)


def split_lines(text: str) -> list[str]:
    """One value per non-empty line, duplicates dropped, order kept."""
    seen, result = set(), []
    for line in text.splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            result.append(line)
    return result


def expand(base: dict, topics: list[str], products: list[str]) -> list[dict]:
    """Batch variants: every topic x every product (or just topics when no product)."""
    return [{**base, "topic": t, "product": p} for t in topics for p in (products or [""])]
