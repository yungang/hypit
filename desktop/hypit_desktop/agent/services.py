"""The generation services the app can drive. One service decides which models exist, how images are made and
which Hypit Runtime Profile and packages a task's project needs."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = PACKAGE_DIR.parents[1] / "templates" / "director"
PROVIDERS_DIR = PACKAGE_DIR.parents[1] / "providers"


@dataclass(frozen=True)
class GenerationService:
    id: str
    label: str
    seedance_variants: dict[str, str]          # UI model name -> variant understood by @hypit/seedance
    variant_resolutions: dict[str, tuple[str, ...]]
    image_label: str                           # how the prompt names the image model
    image_rules: str                           # extra director rules about making pictures
    runtime_template: str                      # file in templates/director
    dependencies: dict[str, str] = field(default_factory=dict)
    local_packages: tuple[str, ...] = ()       # folders in providers/ installed into the project as copies
    programs: tuple[str, ...] = ()             # local helper programs to start (endpoint ids)
    credential_env: str = ""                   # environment variable the Worker reads the service key from


HYPIHUB = GenerationService(
    id="hypihub", label="HypiHub",
    seedance_variants={
        "Seedance 2.5": "2.5",
        "Seedance 2.0 VIP": "standard",
        "Seedance 2.0 Fast VIP": "fast",
        "Seedance 2.0 Mini": "mini",
        "Seedance 2.0 Mini 体验版": "mini",
    },
    variant_resolutions={"fast": ("480p", "720p"), "mini": ("480p", "720p")},
    image_label="GPT Image 2",
    image_rules="",
    runtime_template="hypit.runtime.json",
    dependencies={"@hypit/gpt-image-kits": "^0.1.1", "@hypit/seedance-kits": "^0.1.1"},
)

# Volcengine Ark, called directly with the employee's own key. The Ark model ids live in providers/ark_models.json
# (shared with the provider generator and the Settings connection check); add a variant here together with its id.
ARK = GenerationService(
    id="ark", label="火山方舟",
    seedance_variants={
        "Seedance 2.5": "2.5",
        "Seedance 2.0 VIP": "standard",
        "Seedance 2.0 Fast VIP": "fast",
        "Seedance 2.0 Mini": "mini",
        "Seedance 2.0 Mini 体验版": "mini",
    },
    variant_resolutions={"fast": ("480p", "720p"), "mini": ("480p", "720p"),
                         "standard": ("480p", "720p", "1080p", "4k"), "2.5": ("480p", "720p", "1080p")},
    image_label="Seedream 5.0(@hypit/seedream)",
    image_rules=(
        "7. 所有图片(人物、商品、场景)都用 `@hypit/seedream` 生成,先运行 `hypit vocabulary @hypit/seedream` 看写法;"
        "`quality` 用 basic,`output-format` 用 png。**不要使用 gpt-image,也不要引用 @hypit/gpt-image-kits**:这个环境里没有它们。\n"
        "**含人脸的图片只能用 `seedream:TextImage`(纯文生图)**:Seedance 只信任方舟文生图得到的人脸图片,"
        "`seedream:ReferenceImage`(图生图)生成的人脸图片传给 Seedance 会被拒绝。所以:"
        "需要人物一致时,每张含人脸的图都用 TextImage,并在每个提示词里重复同一段完整的人物外貌描述(发型、眼镜、衣服、年龄、气质);"
        "不要把一张人物图当作 `seedream:Reference` 去生成另一张含人脸的图。"
        "不含人脸的图(商品、背景、物件特写)可以用 ReferenceImage。\n"
        "8.生成服务只有 `ark.default`(视频和图片)和本地服务(语音对齐、媒体处理、渲染)。"
        "不要配置、登录或切换任何服务,不要改 hypit.runtime.json。\n"
        "9. 带真人面孔的参考图片会被服务拒绝:参考图用 Seedream 生成的虚构人物,不要把参考视频里的真人画面当作参考输入。\n"
    ),
    runtime_template="hypit.runtime.ark.json",
    dependencies={"@hypit/seedance-kits": "^0.1.1", "@hypit/seedream": "*"},
    local_packages=("provider-ark",),
    programs=("whisperx.local",),
    credential_env="ARK_API_KEY",
)

SERVICES = {service.id: service for service in (HYPIHUB, ARK)}


def service_by_id(service_id: str) -> GenerationService:
    return SERVICES.get(service_id or "hypihub", HYPIHUB)


# Providers offered in Settings whose generation is not wired up. Selecting one keeps the key and its connection test
# working but stops a task before anything is spent.
PLANNED = {
    "openai": ("OpenAI", "OpenAI 的图片和视频生成还没有接入(需要单独写 Hypit 接入包)。请改用火山方舟。"),
    "gemini": ("Google Gemini", "Gemini 的图片和视频生成还没有接入(需要单独写 Hypit 接入包)。请改用火山方舟。"),
    "grok": ("xAI Grok", "Grok 的图片和视频生成还没有接入(需要单独写 Hypit 接入包)。请改用火山方舟。"),
}


def unsupported_reason(service_id: str) -> str:
    """Why this generation service cannot run yet, or '' when it can. An id nobody offers any more (say, one saved by an
    older version) is refused too, so it never falls back to another service and spends money there."""
    if service_id in PLANNED:
        return PLANNED[service_id][1]
    if not service_id or service_id in SERVICES:
        return ""
    return "设置里选的生成服务已经不再提供,请到「设置」里改用火山方舟。"


# The generation providers shown in Settings: (id, label, the environment variable older setups kept the key in).
GENERATION_CHOICES = [
    ("ark", "火山方舟(Seedance 视频 + Seedream 图片)", "ARK_API_KEY"),
    ("openai", "OpenAI(暂未接入)", "OPENAI_API_KEY"),
    ("gemini", "Google Gemini(暂未接入)", "GEMINI_API_KEY"),
    ("grok", "xAI Grok(暂未接入)", "XAI_API_KEY"),
]
