"""What the app asks the director agent to do. Plain text, kept in one place so it can be tuned."""
from __future__ import annotations

import re

from ..briefs import normalize
from ..hypit import ark_prices
from .models import ModelPlan

SOURCE_PATH = "productions/main/authors/main.svml"
RUN_PATH = "productions/main/runs/main.svrun"
REFERENCE_PATH = "reference/source.mp4"
ASSET_PATHS = {"role_image": "assets/role", "product_image": "assets/product", "background_image": "assets/background"}

SYSTEM_APPEND = (
    "你在一个独立的 Hypit 项目目录里工作,只在这个目录里读写文件。用中文和用户交流。"
    "遇到被护栏拒绝的命令不要重试,直接继续能做的部分,并在最后的总结里说明。"
)


def _list_replacements(images: dict[str, str]) -> str:
    labels = {
        "role_image": ("角色图", "作为主要人物的外貌参考(person-reference=\"true\"),所有镜头里这个人物必须和它一致"),
        "product_image": ("商品图", "作为商品的参考图,画面里出现的商品必须和它一致"),
        "background_image": ("背景图", "作为主要场景的参考图,场景风格和空间要和它一致"),
    }
    lines = [f"- {labels[key][0]}:{path}。{labels[key][1]}" for key, path in images.items()]
    return "\n".join(lines) if lines else "- 没有提供。人物、商品、场景都由你按参考视频的风格重新设计。"


CLIP_SECONDS_FACTOR = 1.25   # generated video seconds allowed per second of the finished video
MIN_TAKE_SECONDS = 4         # the shortest Seedance clip
PRICE_NAMES = {"standard": "seedance-2", "fast": "seedance-2-fast", "mini": "seedance-2-mini", "2.5": "seedance-2.5"}


def _target_seconds(duration: str) -> int:
    match = re.search(r"\d+", duration or "")
    return int(match.group()) if match else 15


def _cost_rule(brief: dict, models: ModelPlan, number: int) -> str:
    """Seedance is billed per generated second; tell the director the price and a hard cap so it plans for cost."""
    seconds = _target_seconds(brief["duration"])
    cap = max(MIN_TAKE_SECONDS, int(seconds * CLIP_SECONDS_FACTOR + 0.999))
    price = ark_prices.seedance_cost(PRICE_NAMES.get(models.variant, "seedance-2-mini"),
                                     {"resolution": models.resolution, "duration": 1}, {}, [])
    return (f"{number}. **控制生成成本**:Seedance 按生成的秒数计费,{models.resolution} 约 {price:.2f} 元/秒。"
            f"所有 Seedance 请求的 duration 之和**不得超过 {cap} 秒**(成片约 {seconds} 秒的 {CLIP_SECONDS_FACTOR:g} 倍)。"
            f"每段 duration 取刚好覆盖这个镜头的最短值(最短 {MIN_TAKE_SECONDS} 秒),说台词的镜头按台词时长取整(用 hypit estimate 估);"
            "不要为同一段内容生成备选版本,成片里每个生成的镜头都要真正用到。"
            "没有人物说话的插入镜头(物件、环境、过渡)优先用 `seedream:TextImage` 的静态图加缓慢推近(clip 的 motion)来做,"
            "不要为它们生成 Seedance 视频。最后在总结里写出你的 Seedance 总秒数和按上面单价算出的视频费用。\n")


def _final_rules(brief: dict, models: ModelPlan) -> str:
    """Service-specific rules come first (numbered from 7); the summary rule is always last."""
    extra = models.service.image_rules
    if not extra:
        return "7. 最后用不超过 12 行总结:创作方案、请求清单、预估花费、不确定的地方和风险。"
    cost = _cost_rule(brief, models, 10) if models.service.id == "ark" else ""
    last = 11 if cost else 10
    return f"{extra}{cost}{last}. 最后用不超过 12 行总结:创作方案、请求清单、预估花费、不确定的地方和风险。"


def build_task_prompt(brief: dict, models: ModelPlan, images: dict[str, str], max_turns: int) -> str:
    b = normalize(brief)
    scene = b["scene"] or "沿用参考视频的场景风格,按新主题重新设计"
    aspect = "与参考视频一致" if b["aspect"] == "源比例" else b["aspect"]
    extra = f"\n## 用户的补充要求\n{b['extra_prompt']}\n" if b["extra_prompt"] else ""
    return f"""请使用 hypit skill,为下面的需求写出完整的 Hypit 制作(Source 和 Run),并让 `hypit check` 通过。
应用会在你完成后统一估价、请用户确认,再由它提交生成。**你不要运行 hypit build / auth / download**(会被拒绝)。

## 参考视频
`{REFERENCE_PATH}`(应用已经准备好)。你要自己去看它:抽帧、读台词和字幕、找镜头切点,理解它为什么有效;不要凭想象。

## 复刻需求
- 新主题:{b['topic']}
- 场景与风格:{scene}
- 目标市场:{b['market']};语言:{b['language']}(台词、配音、字幕都用这个语言)
- 画面比例:{aspect};分辨率:{models.resolution};总时长约 {b['duration']}
- 视频模型:Seedance(变体 {models.variant}),图片模型:{models.service.image_label}

## 替换素材
{_list_replacements(images)}
{extra}
## 硬性规则
1. 文件位置固定:Source 写到 `{SOURCE_PATH}`,Run 写到 `{RUN_PATH}`(目标输出 final.video)。别的文件(配方、笔记)放在 `productions/main/` 下。
2. 保留参考视频的结构机制,替换人物、场景、产品和台词;不要照搬原视频的品牌或标志。
3. 字幕字体用已安装的 `{models.font_package}`。**所有字幕样式的 tail-frames 必须是 0**:最后一个词可能说到最后一帧,停留帧会让字幕超出时间线导致合成失败。
4. 每个 Seedance 请求的参考图和视频必须声明 person-reference。时长要用 `hypit estimate` 按目标语言估算。
5. 你的回合数有限(约 {max_turns} 个):读最必要的几份参考文档,尽快动手写 Source,不要研究系统环境或字体文件。
6. 写完后依次运行 `hypit check`(Source 和 Run)、`hypit plan`、`hypit pricing`。有报错就读报错自己修。
{_final_rules(b, models)}"""


def build_repair_prompt(kind: str, message: str) -> str:
    return f"""刚才提交生成后,在合成阶段失败了(类型:{kind})。失败原因:

{message}

请只修改 Source(`{SOURCE_PATH}`)或它引用的样式配方来解决这个问题,保持已经满意的内容不变;改完运行 `hypit check`(Source 和 Run)。
已经生成的图片、视频、配音会由应用自动复用,不会重复付费,所以不要为了绕开问题而重新设计画面。不要运行 build。最后用不超过 5 行说明你改了什么。"""


def build_feedback_prompt(feedback: str, at_seconds: float | None, parent_build: str, max_turns: int) -> str:
    where = f"(针对成片约 {at_seconds:g} 秒处)" if at_seconds is not None else ""
    reuse = (f"上一次成功的 Build 是 `{parent_build}`。" if parent_build else "没有记录到上一次成功的 Build。")
    return f"""用户看了上一版成片,不满意,反馈如下{where}:

「{feedback}」

请只改动需要改的部分,其余保持不变:
1. 先读 `productions/main/` 里的笔记和当前的 Source/Run,必要时用 `hypit inspect`、`hypit builds` 看上一次的产物。{reuse}
2. 修改 Source。没有改动的素材要在 Run 文件(`{RUN_PATH}`)里用 `build-record` 加 `satisfy` 复用上一次 Build 的产物,避免重新付费;被改动的部分才重新生成。
3. 运行 `hypit check`(Source 和 Run)、`hypit plan`、`hypit pricing`,让预估费用只包含真正要重新生成的内容。
4. 不要运行 build。回合数有限(约 {max_turns} 个)。最后用不超过 8 行总结改了什么、预估再花多少。"""
