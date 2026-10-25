"""Which of the models offered in the UI the Hypit backend can actually run today."""
from __future__ import annotations

from dataclasses import dataclass

from ..briefs import normalize

# UI name -> Seedance variant understood by @hypit/seedance (standard | fast | mini | 2.5)
SEEDANCE_VARIANTS = {
    "Seedance 2.5": "2.5",
    "Seedance 2.0 VIP": "standard",
    "Seedance 2.0 Fast VIP": "fast",
    "Seedance 2.0 Mini": "mini",
    "Seedance 2.0 Mini 体验版": "mini",
}
SEEDANCE_RESOLUTIONS = ("480p", "720p", "1080p")

# CJK captions need a CJK face; other languages can use the Latin face the examples use.
FONT_PACKAGES = {
    "中文": "@fontsource-variable/noto-sans-sc",
    "日本語": "@fontsource-variable/noto-sans-jp",
    "한국어": "@fontsource-variable/noto-sans-kr",
}
LATIN_FONT_PACKAGE = "@fontsource-variable/montserrat"


@dataclass(frozen=True)
class ModelPlan:
    variant: str          # Seedance variant for the Source
    resolution: str
    font_package: str
    problems: tuple[str, ...]


def plan_models(brief: dict) -> ModelPlan:
    b = normalize(brief)
    problems = []
    variant = SEEDANCE_VARIANTS.get(b["model"], "")
    if not variant:
        supported = "、".join(SEEDANCE_VARIANTS)
        problems.append(f"模型「{b['model']}」暂时还不能真实生成。目前可用:{supported}。请回到任务里改一下模型。")
    if b["resolution"] not in SEEDANCE_RESOLUTIONS:
        problems.append(f"分辨率 {b['resolution']} 视频模型不支持,请改成 {'、'.join(SEEDANCE_RESOLUTIONS)} 之一。")
    return ModelPlan(variant, b["resolution"], FONT_PACKAGES.get(b["language"], LATIN_FONT_PACKAGE), tuple(problems))
