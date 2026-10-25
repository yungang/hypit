"""Third validation: can a cheap model follow the real Hypit Skill and write a Source that checks and plans?

This is the target architecture in miniature: Claude Agent SDK (the Claude Code engine) pointed at DeepSeek's
Anthropic-compatible endpoint, with the real Hypit Skill loaded in a scratch project. A guard stands in for the
`hypit` command and refuses anything that spends money, so the only cost is the LLM calls.

    python experiments/skill_probe.py --reference D:\\path\\final.mp4

Needs DEEPSEEK_API_KEY in the environment and `pip install claude-agent-sdk`. Everything is created under
--workspace (default D:\\Dev\\hypit-projects\\agent-test); nothing else on the machine is touched."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DESKTOP = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = Path(r"D:\Dev\hypit-projects\agent-test")
DEFAULT_LAUNCHER = r"D:\Dev\hypit-runtime\node_modules\@hypit\hypit\bin\hypit.mjs"
GIT_BASH = r"D:\Program Files\Git\bin\bash.exe"
BASE_URL = "https://api.deepseek.com/anthropic"
MODEL = "deepseek-flash"

TASK = """这是一次**只读测试**:请使用 hypit skill 完成下面的任务。系统有护栏,build、auth、download、transcribe 等会花钱或改环境的命令会被拒绝,
不要尝试绕过;做到 hypit plan 和 hypit pricing 就停,不要提交 build。

参考视频:reference/source.mp4(本地文件,19 秒竖屏双人播客,你需要自己看它,不要凭想象)。
需求:把它复刻成主题「程序员的一天」。保留原视频的结构机制(强提问 → 揭晓 → 多场景快切 → 吐槽 → 反转),
人物换成一位女程序员和一位男同事,她离不开的产品换成「咖啡」,语言中文,9:16,总长约 15 到 19 秒,
视频用 Seedance 2 Mini 720p,图片用 GPT Image 2。

交付:
1. 在当前目录(已是 Hypit 项目,Runtime Profile 是 ./hypit.runtime.json 且已选中)写好 Source(.svml)和 Run(.svrun),`hypit check` 通过。
2. 运行 `hypit plan` 和 `hypit pricing`,拿到请求清单和价格预估。
3. 最后用不超过 15 行总结:创作方案、预估花费、你不确定的地方和风险。"""

CONTINUE_TASK = ("继续上次的任务。你已经读过参考视频和 Skill、写好了 BRIEF 和 TREATMENT。现在不要再做调研,"
                 "直接写出 Source(.svml)和 Run(.svrun),运行 hypit check,有错就读报错修好,通过后运行 hypit plan 和 hypit pricing,"
                 "最后用不超过 15 行总结。")

APPEND = ("测试环境说明:当前目录是独立的测试项目;只在这个目录里读写文件。用户用中文交流,请用中文汇报。"
          "遇到被护栏拒绝的命令,不要重试,直接在总结里说明你本来要运行什么。"
          "你的回合数有限(约 150 个):读最必要的几份参考文档,尽快动手写 Source,不要研究系统环境或字体文件。"
          "中文字幕需要中日韩字体,项目里已安装 @fontsource-variable/noto-sans-sc,请直接使用。")

SAFE_BASH = {"hypit", "ls", "dir", "cat", "head", "tail", "wc", "pwd", "echo", "mkdir", "cp", "grep", "find",
             "which", "type", "test", "sort", "diff", "npm", "cd", "command", "ffprobe", "printf", "basename",
             "dirname", "realpath", "true"}
OPERATORS = {"&&", "||", ";", "|", "&", ">", ">>", "2>&1", "<"}
SAFE_NPM = ("npm install", "npm ls", "npm view", "npm exec --no -- hypit", "npm list")


def run(cmd: list[str], cwd: Path, **kw) -> str:
    done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=900, env={**os.environ, "NODE_USE_ENV_PROXY": "1"}, **kw)
    if done.returncode != 0:
        sys.exit(f"setup step failed: {' '.join(cmd)}\n{done.stdout}\n{done.stderr}")
    return done.stdout


def setup(workspace: Path, reference: Path, launcher: str) -> None:
    """Create (once) the scratch project: manifest, dependencies, runtime profile, skill, guard, reference."""
    template = DESKTOP / "templates" / "podcast"
    workspace.mkdir(parents=True, exist_ok=True)
    if not (workspace / "package.json").is_file():
        manifest = json.loads((template / "package.json").read_text(encoding="utf-8"))
        manifest["name"] = "agent-test"
        (workspace / "package.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_path = workspace / "package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    font = "@fontsource-variable/noto-sans-sc"
    if font not in manifest.get("dependencies", {}):
        manifest.setdefault("dependencies", {})[font] = "^5.3.0"   # Chinese captions need a CJK face
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not (workspace / "node_modules" / "@fontsource-variable" / "noto-sans-sc").is_dir():
        print("installing the kit packages and the Chinese font the Skill's examples use (npm)...")
        run([shutil.which("npm") or "npm", "install", "--no-audit", "--no-fund"], workspace)
    if not (workspace / "hypit.runtime.json").is_file():
        shutil.copy2(template / "hypit.runtime.json", workspace / "hypit.runtime.json")
    if not (workspace / ".hypit" / "runtime").is_file():
        run(["node", launcher, "runtime", "use", "./hypit.runtime.json"], workspace)
    skill = workspace / ".claude" / "skills" / "hypit"
    if not skill.is_dir():
        shutil.copytree(REPO / "skills" / "hypit", skill)
    ref = workspace / "reference" / "source.mp4"
    if not ref.is_file():
        ref.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reference, ref)
    # the guard that stands in for the `hypit` command
    bin_dir = workspace / "bin"
    bin_dir.mkdir(exist_ok=True)
    shutil.copy2(DESKTOP / "experiments" / "guard" / "hypit_guard.py", bin_dir / "hypit_guard.py")
    python = Path(sys.executable).as_posix()
    guard = (bin_dir / "hypit_guard.py").as_posix()
    (bin_dir / "hypit").write_text(f'#!/usr/bin/env bash\nexec "{python}" "{guard}" "$@"\n', encoding="utf-8", newline="\n")
    (bin_dir / "hypit.cmd").write_text(f'@"{python}" "{guard}" %*\r\n', encoding="utf-8")


def bash_allowed(command: str) -> bool:
    """Every command in a chain must be on the list; quoting is respected (a `|` inside a regex is not a pipe)."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    segment: list[str] = []
    for token in tokens + [";"]:
        if token in OPERATORS - {">", ">>", "2>&1", "<"}:
            if segment and segment[0] not in SAFE_BASH:
                return False
            if segment and segment[0] == "npm" and not " ".join(segment).startswith(SAFE_NPM):
                return False
            segment = []
        else:
            segment.append(token)
    return not any(".." in token for token in tokens)   # no walking out of the project


async def main_async(args) -> None:
    from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                                  PermissionResultDeny, ResultMessage)

    workspace = args.workspace.resolve()
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        sys.exit("Set DEEPSEEK_API_KEY first.")
    setup(workspace, args.reference, args.launcher)
    out = DESKTOP / "experiments" / "out" / f"skill-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    transcript = (out / "transcript.jsonl").open("w", encoding="utf-8")
    denied: list[str] = []

    async def can_use_tool(name: str, tool_input: dict, context):
        if name == "Bash":
            command = tool_input.get("command", "")
            if not bash_allowed(command):
                denied.append(command)
                return PermissionResultDeny(message=f"Command not allowed in this test: {command[:80]}")
        if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            target = Path(tool_input.get("file_path", "")).resolve()
            if workspace not in target.parents and target != workspace:
                denied.append(f"{name} {target}")
                return PermissionResultDeny(message="Writing outside the test project is not allowed.")
        if name in ("WebFetch", "WebSearch", "Task"):
            return PermissionResultDeny(message=f"{name} is disabled in this test.")
        return PermissionResultAllow()

    env = {
        "ANTHROPIC_BASE_URL": BASE_URL, "ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": MODEL, "ANTHROPIC_DEFAULT_OPUS_MODEL": MODEL, "ANTHROPIC_DEFAULT_SONNET_MODEL": MODEL,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": MODEL, "CLAUDE_CODE_SUBAGENT_MODEL": MODEL,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "NODE_USE_ENV_PROXY": "1",
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "900000",   # DeepSeek's window is 1M; Claude Code does not know the model
        "PATH": str(workspace / "bin") + os.pathsep + os.environ.get("PATH", ""),
        "HYPIT_GUARD_WORKSPACE": str(workspace), "HYPIT_LAUNCHER": args.launcher,
    }
    if Path(GIT_BASH).is_file():
        env["CLAUDE_CODE_GIT_BASH_PATH"] = GIT_BASH
    options = ClaudeAgentOptions(
        cwd=str(workspace), model=MODEL, env=env, max_turns=args.max_turns, continue_conversation=args.resume,
        system_prompt={"type": "preset", "preset": "claude_code", "append": APPEND},
        setting_sources=["project"], skills="all",
        # Only read-only tools are pre-approved. Anything listed here skips can_use_tool, so Bash/Write/Edit
        # must stay out of the list for the permission check below to see them.
        allowed_tools=["Read", "Glob", "Grep", "Skill", "TodoWrite"],
        can_use_tool=can_use_tool,
        max_buffer_size=64 * 1024 * 1024,   # a tool result holding an image is far bigger than the 1 MiB default
    )

    started, turns, final = time.time(), 0, ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(CONTINUE_TASK if args.resume else TASK)
        async for message in client.receive_response():
            transcript.write(json.dumps({"type": type(message).__name__, "repr": repr(message)[:6000]},
                                        ensure_ascii=False) + "\n")
            name = type(message).__name__
            for block in getattr(message, "content", None) or []:
                kind = type(block).__name__
                if kind == "ToolUseBlock":
                    turns += 1
                    detail = json.dumps(block.input, ensure_ascii=False)
                    print(f"[{turns:2}] {block.name} {detail[:170]}")
                elif kind == "TextBlock" and name == "AssistantMessage":
                    final = block.text
                elif kind == "ToolResultBlock" and getattr(block, "is_error", False):
                    print(f"      ! tool error: {str(block.content)[:160]}")
            if isinstance(message, ResultMessage):
                usage = message.usage or {}
                print(f"\nresult: {message.subtype}, turns={message.num_turns}, "
                      f"{(time.time() - started):.0f}s, usage={json.dumps(usage)[:300]}")
    (out / "final_answer.txt").write_text(final, encoding="utf-8")

    print("\n=== what the agent left in the project ===")
    for pattern in ("*.svml", "*.svrun", "*.svs"):
        for path in sorted(workspace.glob(pattern)):
            print(f"  {path.name} ({path.stat().st_size} bytes)")
    guard_log = workspace / "guard.log"
    calls = [json.loads(line) for line in guard_log.read_text(encoding="utf-8").splitlines()] if guard_log.is_file() else []
    blocked = [c["argv"] for c in calls if not c["allowed"]]
    print(f"hypit calls through the guard: {len(calls)}, blocked: {len(blocked)} {blocked[:5]}")
    print(f"commands refused by the permission check: {len(denied)} {denied[:3]}")
    print(f"\nfinal answer ({len(final)} chars) saved to {out / 'final_answer.txt'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", type=Path, required=True, help="the reference video to copy into the project")
    ap.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    ap.add_argument("--launcher", default=os.environ.get("HYPIT_LAUNCHER", DEFAULT_LAUNCHER))
    ap.add_argument("--max-turns", type=int, default=150)
    ap.add_argument("--continue", dest="resume", action="store_true",
                    help="continue the previous conversation in this workspace instead of starting over")
    ap.add_argument("--setup-only", action="store_true", help="create the project and guard, then stop (no key needed)")
    args = ap.parse_args()
    if args.setup_only:
        setup(args.workspace.resolve(), args.reference, args.launcher)
        print(f"workspace ready: {args.workspace.resolve()}")
        return
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
