"""Runs the director agent (Claude Agent SDK -> an Anthropic-compatible model) and turns what it does into events.

The SDK is asynchronous and the app's backends are synchronous generators running on a worker thread, so the
agent runs on its own event loop in a helper thread and hands events over through a queue."""
from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

from ..events import Event
from .prompts import SYSTEM_APPEND

SAFE_BASH = {"hypit", "ls", "dir", "cat", "head", "tail", "wc", "pwd", "echo", "mkdir", "cp", "grep", "find", "which",
             "type", "test", "sort", "diff", "npm", "cd", "command", "ffprobe", "printf", "basename", "dirname",
             "realpath", "true"}
SAFE_NPM = ("npm install", "npm ls", "npm view", "npm exec --no -- hypit", "npm list")
OPERATORS = {"&&", "||", ";", "|", "&"}
REDIRECTS = {">", ">>", "2>&1", "<"}
GIT_BASH_CANDIDATES = (r"D:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe")
_DONE = object()
GIVE_UP_SECONDS = 20.0


def bash_allowed(command: str) -> bool:
    """Every command in a chain must be on the list; quoting is respected and nothing may leave the project."""
    import shlex
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    segment: list[str] = []
    for token in tokens + [";"]:
        if token in OPERATORS:
            if segment and segment[0] not in SAFE_BASH:
                return False
            if segment and segment[0] == "npm" and not " ".join(segment).startswith(SAFE_NPM):
                return False
            segment = []
        elif token not in REDIRECTS:
            segment.append(token)
    return not any(".." in token for token in tokens)


# --- turning SDK messages into friendly events ------------------------------------------------------------
def describe_tool(name: str, tool_input: dict) -> str:
    """One short Chinese phrase for what the agent is doing."""
    if name == "Skill":
        return "读取 Hypit 制作指南"
    if name in ("Read", "Grep", "Glob"):
        target = str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern") or "")
        if "reference" in target and target.lower().endswith((".jpg", ".png")):
            return "查看参考视频的画面"
        return "阅读参考资料"
    if name in ("Write", "Edit", "MultiEdit"):
        return f"写入 {Path(str(tool_input.get('file_path', ''))).name or '文件'}"
    if name == "Bash":
        command = str(tool_input.get("command", ""))
        for needle, text in (("media tile", "查看参考视频的画面"), ("media frames", "查看参考视频的画面"),
                             ("media boundaries", "检测参考视频的镜头切换"), ("media probe", "读取参考视频信息"),
                             ("estimate", "估算台词时长"), ("pricing", "查询价格"), ("plan", "规划生成请求"),
                             ("check", "检查脚本"), ("vocabulary", "查阅制作词汇"), ("transcribe", "识别参考视频的台词"),
                             ("npm install", "安装依赖")):
            if needle in command:
                return text
        return "执行命令"
    if name == "TodoWrite":
        return "整理工作计划"
    return f"使用工具 {name}"


def translate(message, counter: list[int]) -> list[Event]:
    """Events for one SDK message. `counter` holds the running number of tool calls (one-element list)."""
    events: list[Event] = []
    kind = type(message).__name__
    if kind == "AssistantMessage":
        for block in message.content or []:
            block_kind = type(block).__name__
            if block_kind == "TextBlock" and block.text.strip():
                events.append(Event("message", {"role": "agent", "text": block.text.strip()}))
            elif block_kind == "ToolUseBlock":
                counter[0] += 1
                events.append(Event("step", {"id": "director", "state": "running",
                                             "title": f"AI 导演工作中:{describe_tool(block.name, block.input or {})}"
                                                      f"(第 {counter[0]} 步)"}))
    return events


@dataclass
class PhaseResult:
    ok: bool = False
    summary: str = ""
    turns: int = 0
    error: str = ""
    usage: dict = field(default_factory=dict)


class Director:
    def __init__(self, workspace: Path, api_key: str, base_url: str, model: str, launcher: str, node: str,
                 max_turns: int = 150, use_env_proxy: bool = True, sdk=None):
        self.workspace, self.api_key, self.base_url, self.model = Path(workspace), api_key, base_url, model
        self.launcher, self.node, self.max_turns, self.use_env_proxy = launcher, node, max_turns, use_env_proxy
        self._sdk = sdk  # injected in tests

    # --- the SDK side -------------------------------------------------------------------------------
    def _options(self, resume: bool, sdk):
        env = {
            "ANTHROPIC_BASE_URL": self.base_url, "ANTHROPIC_AUTH_TOKEN": self.api_key, "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": self.model, "ANTHROPIC_DEFAULT_OPUS_MODEL": self.model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": self.model, "ANTHROPIC_DEFAULT_HAIKU_MODEL": self.model,
            "CLAUDE_CODE_SUBAGENT_MODEL": self.model, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "900000",
            "PATH": str(self.workspace / "bin") + os.pathsep + os.environ.get("PATH", ""),
            "HYPIT_GUARD_WORKSPACE": str(self.workspace), "HYPIT_LAUNCHER": self.launcher,
        }
        if self.use_env_proxy:
            env["NODE_USE_ENV_PROXY"] = "1"
        for candidate in GIT_BASH_CANDIDATES:
            if Path(candidate).is_file():
                env["CLAUDE_CODE_GIT_BASH_PATH"] = candidate
                break
        workspace = self.workspace.resolve()

        async def can_use_tool(name: str, tool_input: dict, context):
            if name == "Bash" and not bash_allowed(tool_input.get("command", "")):
                return sdk.PermissionResultDeny(message="This command is not allowed here; use the hypit command instead.")
            if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                target = Path(tool_input.get("file_path", "")).resolve()
                if workspace not in target.parents and target != workspace:
                    return sdk.PermissionResultDeny(message="Write only inside the project directory.")
            if name in ("WebFetch", "WebSearch", "Task"):
                return sdk.PermissionResultDeny(message=f"{name} is not available.")
            return sdk.PermissionResultAllow()

        return sdk.ClaudeAgentOptions(
            cwd=str(self.workspace), model=self.model, env=env, max_turns=self.max_turns, continue_conversation=resume,
            system_prompt={"type": "preset", "preset": "claude_code", "append": SYSTEM_APPEND},
            setting_sources=["project"], skills="all",
            # only read-only tools are pre-approved; everything else passes through can_use_tool
            allowed_tools=["Read", "Glob", "Grep", "Skill", "TodoWrite"],
            can_use_tool=can_use_tool, max_buffer_size=64 * 1024 * 1024)

    async def _run_async(self, prompt: str, resume: bool, out: "queue.Queue", stop: threading.Event,
                         result: PhaseResult) -> None:
        sdk = self._sdk
        if sdk is None:
            import claude_agent_sdk as sdk  # noqa: PLC0415 - heavy import, only when a director really runs
        counter = [0]
        last_text = ""
        try:
            async with sdk.ClaudeSDKClient(options=self._options(resume, sdk)) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    if stop.is_set():
                        await client.interrupt()
                        break
                    for event in translate(message, counter):
                        out.put(event)
                        if event.type == "message":
                            last_text = event.data["text"]
                    if type(message).__name__ == "ResultMessage":
                        result.turns = message.num_turns
                        result.usage = dict(message.usage or {})
                        result.ok = message.subtype == "success" and not message.is_error
                        if not result.ok:
                            result.error = f"导演没有在限定回合内完成({message.subtype})"
        except Exception as exc:  # the SDK raises for engine, auth and network trouble
            result.error = f"{type(exc).__name__}: {exc}"
        result.summary = last_text
        out.put(_DONE)

    # --- the synchronous side -----------------------------------------------------------------------
    def run_phase(self, prompt: str, resume: bool, cancelled: Callable[[], bool],
                  result: PhaseResult) -> Iterator[Event]:
        """Yield events while the agent works. Fills `result` when it finishes (or is cancelled)."""
        out: queue.Queue = queue.Queue()
        stop = threading.Event()
        thread = threading.Thread(
            target=lambda: asyncio.run(self._run_async(prompt, resume, out, stop, result)), daemon=True)
        thread.start()
        stop_requested_at = 0.0
        while True:
            try:
                item = out.get(timeout=0.3)
            except queue.Empty:
                if cancelled():
                    if not stop.is_set():
                        stop.set()
                        stop_requested_at = time.monotonic()
                    if time.monotonic() - stop_requested_at > GIVE_UP_SECONDS:  # the engine is stuck; stop waiting for it
                        result.error = "已取消"
                        break
                continue
            if item is _DONE:
                break
            yield item
        thread.join(timeout=5)
        yield Event("step", {"id": "director", "state": "done" if result.ok else "failed",
                             "title": "AI 导演完成创作" if result.ok else "AI 导演没有完成"})
