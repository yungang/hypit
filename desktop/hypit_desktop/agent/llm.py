"""AI director providers offered in Settings. The director runs on the Claude Agent SDK, so it needs an endpoint that
speaks the Anthropic Messages protocol with tool use and image input. DeepSeek (validated end to end) and Anthropic
itself qualify; OpenAI's API is a different protocol and needs a translating gateway that is not built yet."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmProvider:
    id: str
    label: str
    base_url: str
    model: str
    auth: str = "bearer"          # how the key is sent to the endpoint: "bearer" (Authorization) or "x-api-key"
    max_context: int = 0          # CLAUDE_CODE_MAX_CONTEXT_TOKENS for the engine; 0 leaves it unset
    runnable: bool = True
    note: str = ""                # shown in Settings when something is missing
    env_var: str = ""             # the variable older setups kept the key in


LLM_PRESETS = {
    "deepseek": LlmProvider("deepseek", "DeepSeek(推荐,已验证)", "https://api.deepseek.com/anthropic", "deepseek-flash",
                            auth="bearer", max_context=900_000, env_var="DEEPSEEK_API_KEY"),
    "anthropic": LlmProvider("anthropic", "Anthropic(Claude)", "https://api.anthropic.com", "claude-sonnet-5-5",
                             auth="x-api-key", env_var="ANTHROPIC_API_KEY"),
    "openai": LlmProvider("openai", "OpenAI", "https://api.openai.com/v1", "gpt-5", runnable=False, env_var="OPENAI_API_KEY",
                          note="OpenAI 的接口协议和 AI 导演使用的 Anthropic 协议不兼容,需要协议转换网关,暂未接入。"
                               "现在可以保存密钥并测试连接,但还不能用它运行导演。"),
}
CUSTOM_LLM = LlmProvider("custom", "自定义(兼容 Anthropic 接口的服务)", "", "")


def llm_provider(provider_id: str) -> LlmProvider:
    return LLM_PRESETS.get(provider_id) or CUSTOM_LLM
