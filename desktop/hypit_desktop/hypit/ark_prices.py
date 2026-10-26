"""Volcengine Ark prices, from https://ark.volcengine.com/region:cn-beijing/docs/model-pricing (checked 2026-10-26).

Ark bills Seedance per token and Seedream per image, in yuan. `hypit pricing` only links the price page for this
provider, so the app prices requests itself. Keep the numbers in step with the official page.

Seedance tokens = seconds x width x height x 24 fps / 1024, where seconds are the output length plus any input video.
The official examples reproduce exactly with the pixel areas below (for instance Mini, 720p, 5 s: 108,000 tokens x 23
yuan per million = 2.48 yuan)."""
from __future__ import annotations

PROVIDER_PACKAGE = "@hypit-desktop/provider-ark"
CNY_PER_USD = 7.2            # only used to show an approximate dollar figure and to keep the ledger in one unit
FPS = 24
SAFETY = 1.03                # real usage came out 1% above the formula in a measured 4 s 480p clip

# Pixels of one frame per resolution tier (the 480p tier is 864x496 / 496x864; the others are the usual sizes).
FRAME_AREA = {"480p": 864 * 496, "720p": 1280 * 720, "1080p": 1920 * 1080, "4k": 3840 * 2160}

# yuan per million tokens: (input without video, input with video)
SEEDANCE_PRICES = {
    "seedance-2": {"480p": (46, 28), "720p": (46, 28), "1080p": (51, 31), "4k": (26, 16)},
    "seedance-2-fast": {"480p": (37, 22), "720p": (37, 22)},
    "seedance-2-mini": {"480p": (23, 14), "720p": (23, 14)},
    "seedance-2.5": {"480p": (70, 42), "720p": (70, 42), "1080p": (77, 46)},
}
# yuan per generated image. The `seedream-5-lite` capability is served by the Seedream 5.0 flash model.
SEEDREAM_PRICES = {"seedream-5-lite": 0.12}
AUTO_DURATION_SECONDS = 15   # when the model chooses the length, price the longest clip


def is_ark(group: dict) -> bool:
    return group.get("use") == PROVIDER_PACKAGE


def seedance_cost(name: str, fields: dict, refs: dict, notes: list[str]) -> float:
    resolution = str(fields.get("resolution", "720p")).lower()
    tiers = SEEDANCE_PRICES.get(name, {})
    if resolution not in tiers:
        notes.append(f"{name}: 没有 {resolution} 的价格,按 720p 计")
        resolution = "720p"
    price = tiers.get(resolution)
    if price is None:
        notes.append(f"{name}: 价目表里没有这个模型,未计入")
        return 0.0
    duration = fields.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        notes.append(f"{name}: 时长由模型自动决定,按 {AUTO_DURATION_SECONDS} 秒估算")
        duration = AUTO_DURATION_SECONDS
    has_video = bool(refs.get("video"))
    if has_video:
        notes.append(f"{name}: 参考视频的时长要生成后才知道,只按输出时长估算")
    tokens = duration * FRAME_AREA[resolution] * FPS / 1024
    return tokens * price[1 if has_video else 0] / 1_000_000 * SAFETY


def seedream_cost(name: str, notes: list[str]) -> float:
    if name not in SEEDREAM_PRICES:
        notes.append(f"{name}: 价目表里没有这个模型,未计入")
        return 0.0
    return SEEDREAM_PRICES[name]


def request_cost(capability: str, fields: dict, refs: dict, notes: list[str]) -> float:
    """Yuan for one request. `capability` looks like `@hypit/seedance@1#seedance-2-mini`."""
    name = capability.split("#", 1)[-1]
    if "/seedance@" in capability:
        return seedance_cost(name, fields, refs, notes)
    if "/seedream@" in capability:
        return seedream_cost(name, notes)
    notes.append(f"{capability}: 价目表里没有这个模型,未计入")
    return 0.0
