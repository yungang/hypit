"""Turn a failed Build's `failure` text into something a user can act on."""
from __future__ import annotations

# (substring that identifies the failure, kind, message shown to the user)
RULES = [
    # Volcengine Ark (matched first: its messages also contain generic "HTTP 401" style text)
    ("InputImageSensitiveContentDetected", "review", "方舟认为参考图里有真人面孔,拒绝了这个请求。需要把人物改成插画、卡通或 3D 风格,或使用方舟授权过的虚拟人像。"),
    ("InputTextSensitiveContentDetected", "review", "方舟审核没有通过提示词里的内容,请调整文案后重试。"),
    ("OutputVideoSensitiveContentDetected", "review", "方舟审核没有通过生成的视频内容,请调整画面描述后重试。"),
    ("AccountOverdueError", "credits", "方舟账户欠费,请到火山引擎控制台充值后点“重新运行”。"),
    ("InsufficientBalance", "credits", "方舟账户余额不足,请到火山引擎控制台充值后点“重新运行”。"),
    ("Ark HTTP 401", "auth", "方舟密钥无效或已失效,请检查设置里的方舟 API Key。"),
    ("Ark HTTP 403", "auth", "方舟没有这个模型的使用权限,请到控制台开通对应模型。"),
    ("ModelNotOpen", "auth", "这个模型还没有在方舟控制台开通,请先开通。"),
    ("Ark HTTP 429", "network", "方舟请求太频繁(429),稍后自动重试。"),
    ("Ark HTTP 500", "network", "方舟服务暂时出错(500)。"),
    ("Ark HTTP 502", "network", "方舟服务暂时不可用(502)。"),
    ("Ark HTTP 503", "network", "方舟服务暂时不可用(503)。"),
    ("Ark HTTP 504", "network", "方舟服务响应超时(504)。"),
    ("insufficient_credits", "credits", "HypiHub 积分不足,请到 hypit.ai 充值后点“重新运行”。"),
    ("HTTP 402", "credits", "HypiHub 积分不足,请到 hypit.ai 充值后点“重新运行”。"),
    ("HTTP 401", "auth", "HypiHub 登录已失效,请重新执行 hypit auth login。"),
    ("RUNTIME_CREDENTIAL_MISSING", "auth", "还没有登录 HypiHub,请先执行 hypit auth login hypihub.default。"),
    ("is outside Timeline", "timeline", "字幕或素材的时间超出了视频长度。生成结果和脚本不匹配,需要调整脚本后重试(已生成的素材可复用,不会再扣费)。"),
    ("Network.enable timed out", "browser", "本地渲染浏览器无法启动,请重新安装渲染浏览器(hypit programs prepare),并检查杀毒软件有没有拦截。"),
    ("HTML browser is unavailable", "browser", "本地渲染浏览器还没有安装,请先运行 hypit programs prepare。"),
    ("ECONNRESET", "network", "网络连接被重置。"),
    ("ETIMEDOUT", "network", "网络超时。"),
    ("fetch failed", "network", "网络请求失败。"),
    ("socket disconnected", "network", "网络连接中断。"),
    ("EAI_AGAIN", "network", "域名解析暂时失败。"),
    ("HTTP 502", "network", "HypiHub 服务暂时不可用(502)。"),
    ("HTTP 503", "network", "HypiHub 服务暂时不可用(503)。"),
    ("HTTP 504", "network", "HypiHub 服务响应超时(504)。"),
    ("Bad gateway", "network", "HypiHub 服务暂时不可用(502)。"),
    ("content_policy", "review", "内容审核未通过,请更换素材或提示词。"),
    ("Risk Not Pass", "review", "内容审核未通过,请更换素材或提示词。"),
]
MAX_DETAIL = 300


def classify(failure: str) -> tuple[str, str]:
    """Return (kind, user message). Unknown failures keep a shortened original text."""
    for needle, kind, message in RULES:
        if needle.lower() in failure.lower():
            return kind, message
    detail = " ".join(failure.split())
    if len(detail) > MAX_DETAIL:
        detail = detail[:MAX_DETAIL] + "…"
    return "other", f"生成失败:{detail}"


# Failures that a re-submission can cure by itself: nothing in the user's request or script is wrong.
TRANSIENT_KINDS = ("network",)
# Failures the director can cure by editing the script.
SCRIPT_KINDS = ("timeline",)


def is_transient(kind: str) -> bool:
    return kind in TRANSIENT_KINDS


def is_script_problem(kind: str) -> bool:
    return kind in SCRIPT_KINDS
