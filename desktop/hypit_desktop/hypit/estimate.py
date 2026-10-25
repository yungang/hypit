"""Estimate a Build's cost from `hypit pricing --json`.

Prices are in HypiHub credits (the pricing document names credits_per_usd). The estimate is a floor
when a quantity is only known after generation (audio seconds, reference-video seconds, automatic
durations); those cases are listed in `incomplete` instead of being guessed."""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CREDITS_PER_USD = 200.0


@dataclass
class Estimate:
    credits: float = 0.0
    credits_per_usd: float = DEFAULT_CREDITS_PER_USD
    paid_requests: int = 0
    incomplete: list[str] = field(default_factory=list)

    @property
    def usd(self) -> float:
        return self.credits / self.credits_per_usd


def _operation(data: dict, refs: dict) -> dict:
    ops = data.get("operations")
    if not ops:
        return data
    wanted = "image-to-image" if refs.get("image") else "text-to-image"
    for op in ops:
        if op.get("operation") == wanted:
            return op
    return ops[0]


def _request_credits(capability: str, data: dict, fields: dict, refs: dict, notes: list[str]) -> float:
    pricing = _operation(data, refs).get("pricing") or {}
    credits = pricing.get("credits") or {}
    mode = pricing.get("mode")
    rates = credits.get("media_rates") or []

    if mode == "per_request":
        return float(credits.get("base", 0))

    if mode == "per_image":
        resolution = str(fields.get("resolution", "")).lower()
        for row in rates:
            if str(row.get("resolution", "")).lower() == resolution:
                return float(row["unit"])
        return float(credits.get("base", 0))

    if mode == "per_second":
        duration = fields.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            notes.append(f"{capability}: 时长由模型自动决定,按 0 秒计")
            return 0.0
        has_video = bool(refs.get("video"))
        resolution = str(fields.get("resolution", "")).lower()
        for row in rates:
            same_flag = bool((row.get("flags") or {}).get("reference_video", False)) == has_video
            if same_flag and str(row.get("resolution", "")).lower() == resolution:
                if has_video:
                    notes.append(f"{capability}: 参考视频的输入秒数要生成后才能计费,未计入")
                return float(row["unit"]) * float(duration)
        notes.append(f"{capability}: 没找到 {resolution} 的单价,按 {credits.get('per_second', 0)} 积分/秒计")
        return float(credits.get("per_second", 0)) * float(duration)

    if mode == "per_audio_second":
        notes.append(f"{capability}: 音频时长生成后才知道,只计基础费")
        return float(credits.get("base", 0))

    notes.append(f"{capability}: 未知计费方式 {mode!r},未计入")
    return 0.0


def estimate(pricing_json: dict) -> Estimate:
    result = Estimate()
    notes: list[str] = []
    for group in pricing_json.get("groups", []):
        capability = group.get("capability", "?")
        docs = group.get("pricingDocuments") or []
        if not docs:
            result.incomplete.append(f"{capability}: 读不到价格,未计入")
            continue
        data = docs[0].get("data") or {}
        result.credits_per_usd = float(data.get("credits_per_usd", result.credits_per_usd))
        for request in group.get("requests", []):
            summary = request.get("summary") or {}
            result.credits += _request_credits(capability, data, summary.get("fields") or {},
                                               summary.get("references") or {}, notes)
            result.paid_requests += 1
    for note in notes:  # one line per distinct explanation
        if note not in result.incomplete:
            result.incomplete.append(note)
    return result
