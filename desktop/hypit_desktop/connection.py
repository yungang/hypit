"""The Settings page's "测试连接" buttons. Each check is free (or one token) and says in plain Chinese what is wrong."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

from .agent.services import PROVIDERS_DIR

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
Result = tuple[bool, str]
Opener = Callable[..., object]


def _post(url: str, body: dict, headers: dict, timeout: float, opener: Optional[Opener]) -> tuple[int, str]:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, str(getattr(error, "reason", error))


def _get(url: str, headers: dict, timeout: float, opener: Optional[Opener]) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, str(getattr(error, "reason", error))


def _code(text: str) -> str:
    try:
        error = json.loads(text).get("error") or {}
        return str(error.get("code") or error.get("type") or "")
    except (ValueError, AttributeError):
        return ""


def test_llm(base_url: str, model: str, key: str, timeout: float = 30, opener: Optional[Opener] = None) -> Result:
    """Ask the AI director's endpoint for one token."""
    if not key:
        return False, "还没有填写密钥。"
    url = base_url.rstrip("/") + "/v1/messages"
    status, text = _post(url, {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
                         {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout, opener)
    if status == 200:
        return True, f"连接正常,模型 {model} 可用。"
    if status == 0:
        return False, f"连不上 {base_url}:{text}。请检查网络或代理。"
    if status in (401, 403):
        return False, "密钥无效或没有权限,请重新复制密钥。"
    if status in (400, 404):
        return False, f"服务器不接受模型名「{model}」:{text[:160]}"
    if status == 429:
        return False, "请求太频繁或额度用完了,请稍后再试或到服务商处充值。"
    return False, f"服务器返回 {status}:{text[:160]}"


SEEDANCE_LABELS = {"seedance-2": "2.0", "seedance-2-fast": "2.0 Fast", "seedance-2-mini": "2.0 Mini", "seedance-2.5": "2.5"}


def ark_models() -> dict[str, str]:
    """Capability -> Ark model id for the Seedance models the app offers (providers/ark_models.json)."""
    models = json.loads((PROVIDERS_DIR / "ark_models.json").read_text(encoding="utf-8"))
    return {name: models[name] for name in SEEDANCE_LABELS if name in models}


def test_ark(key: str, timeout: float = 30, opener: Optional[Opener] = None,
             models: Optional[dict[str, str]] = None) -> Result:
    """Send an incomplete video task per model: a good key answers 'invalid parameter' for an enabled model and
    'not found' for one that is not enabled. Neither is ever billed."""
    if not key:
        return False, "还没有填写密钥。"
    opened, closed = [], []
    for name, model in (models if models is not None else ark_models()).items():
        status, text = _post(ARK_BASE_URL + "/contents/generations/tasks", {"model": model, "content": []},
                             {"Authorization": f"Bearer {key}"}, timeout, opener)
        code = _code(text)
        label = SEEDANCE_LABELS.get(name, name)
        if status == 0:
            return False, f"连不上火山方舟:{text}。请检查网络或代理。"
        if status == 401 or code == "AuthenticationError":
            return False, "方舟密钥无效,请重新复制 API Key。"
        if status == 429:
            return False, "请求太频繁,请稍后再试。"
        if status == 404 or code.startswith("InvalidEndpointOrModel"):
            closed.append(label)
        elif status == 403:
            return False, f"密钥有效,但没有权限使用视频模型({code or '403'})。请到方舟控制台开通。"
        elif status == 400 or code == "InvalidParameter":
            opened.append(label)
        else:
            return False, f"方舟返回 {status}:{text[:160]}"
    if not opened:
        return False, "密钥有效,但 Seedance 模型都还没有开通。请到方舟控制台开通。"
    text = "连接正常,密钥有效。已开通:Seedance " + "、".join(opened) + "。"
    if closed:
        text += f"还没有开通:Seedance {'、'.join(closed)}(用到时会提示)。"
    return True, text


# Providers that only need to prove the key works: a read-only call that lists models. Free, and the keys travel in
# headers, never in the URL.
KEY_CHECKS = {
    "openai": ("OpenAI", "https://api.openai.com/v1/models", lambda key: {"Authorization": f"Bearer {key}"}),
    "grok": ("xAI Grok", "https://api.x.ai/v1/models", lambda key: {"Authorization": f"Bearer {key}"}),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/models",
               lambda key: {"x-goog-api-key": key}),
    "anthropic": ("Anthropic", "https://api.anthropic.com/v1/models",
                  lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"}),
}


def test_key(provider_id: str, key: str, timeout: float = 30, opener: Optional[Opener] = None) -> Result:
    """Is this key accepted by the provider? (No model or billing is touched.)"""
    if not key:
        return False, "还没有填写密钥。"
    name, url, headers = KEY_CHECKS[provider_id]
    status, text = _get(url, headers(key), timeout, opener)
    if status == 200:
        return True, f"连接正常,{name} 密钥有效。"
    if status == 0:
        return False, f"连不上 {name}:{text}。请检查网络或代理。"
    if status in (400, 401, 403):         # a model listing has no parameters to get wrong, so 400 means a bad key too
        return False, f"{name} 不接受这个密钥,请重新复制 API Key。"
    if status == 429:
        return False, f"{name} 请求太频繁或额度用完了,请稍后再试。"
    return False, f"{name} 返回 {status}:{text[:160]}"


def test_anthropic(key: str, base_url: str, model: str, timeout: float = 30, opener: Optional[Opener] = None) -> Result:
    """The key, and whether the chosen Claude model exists for it (a read-only lookup)."""
    if not key:
        return False, "还没有填写密钥。"
    base = (base_url or "https://api.anthropic.com").rstrip("/")
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    status, text = _get(f"{base}/v1/models/{model}", headers, timeout, opener)
    if status == 200:
        return True, f"连接正常,模型 {model} 可用。"
    if status == 404:
        return False, f"密钥有效,但这个账号用不了模型「{model}」。请到设置里换一个模型名。"
    if status == 0:
        return False, f"连不上 Anthropic:{text}。请检查网络或代理。"
    if status in (401, 403):
        return False, "Anthropic 不接受这个密钥,请重新复制 API Key。"
    if status == 429:
        return False, "Anthropic 请求太频繁或额度用完了,请稍后再试。"
    return False, f"Anthropic 返回 {status}:{text[:160]}"


def test_provider(provider_id: str, key: str, base_url: str = "", model: str = "",
                  opener: Optional[Opener] = None) -> Result:
    """The right check for a provider shown in Settings (director or generator)."""
    if provider_id == "ark":
        return test_ark(key, opener=opener)
    if provider_id == "anthropic" and model:
        return test_anthropic(key, base_url, model, opener=opener)
    if provider_id in KEY_CHECKS:
        return test_key(provider_id, key, opener=opener)
    return test_llm(base_url, model, key, opener=opener)        # DeepSeek and custom Anthropic-compatible endpoints
