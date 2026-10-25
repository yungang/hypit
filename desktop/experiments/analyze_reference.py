"""Small validation: can a cheap vision model read a reference video well enough to plan a clone?

It does NOT use the Hypit Skill or any agent loop. It only checks the first, make-or-break ability:
given contact sheets of the video (made by `hypit media tiles`: timestamps + burned-in captions), can the
model describe the structure and write a usable storyboard for a new topic?

    set DEEPSEEK_API_KEY=...                       (cmd)   |   $env:DEEPSEEK_API_KEY = "..."   (PowerShell)
    python experiments/analyze_reference.py path\\to\\video.mp4 --provider deepseek --topic "程序员的一天"

Keys are read from environment variables only. Cost: a few cents.
Standard library only (no extra packages)."""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_LAUNCHER = r"D:\Dev\hypit-runtime\node_modules\@hypit\hypit\bin\hypit.mjs"

# Anthropic-compatible endpoints. price = (input, output) in yuan per million tokens, for a rough cost line.
PROVIDERS = {
    "deepseek": {"base": "https://api.deepseek.com/anthropic", "key_env": "DEEPSEEK_API_KEY",
                 "model": "deepseek-flash", "price": (2.0, 8.0)},   # peak-hour list price, cache miss
    "qwen": {"base": "https://dashscope.aliyuncs.com/apps/anthropic", "key_env": "DASHSCOPE_API_KEY",
             "model": "qwen3.8-flash", "price": None},
}

SYSTEM = ("你是短视频复刻导演。你只能依据给你的画面拼图(每格下方是时间戳,画面里有烧录字幕)理解视频,"
          "不要编造看不到的内容。输出严格的 JSON,不要加任何说明文字或代码块标记。")

TASK = """下面是一条参考视频的画面拼图,时长 {duration:.1f} 秒,每格间隔 {step:g} 秒,格子下方是时间戳。
请分析它,并为新主题「{topic}」写一份复刻方案。输出 JSON,字段:
{{
  "summary": "一句话概括视频讲了什么",
  "format": "视频形式(口播/对话/剧情/展示等)",
  "hook": "开头怎么抓住注意力",
  "structure": [{{"start": 秒, "end": 秒, "purpose": "这一段起什么作用"}}],
  "people": [{{"role": "人物角色", "look": "外貌与穿着", "voice": "声音与说话风格"}}],
  "scenes": [{{"start": 秒, "end": 秒, "location": "场景", "camera": "镜头(景别/角度/运动)", "action": "人物动作", "speech": "能读到的台词"}}],
  "style": "整体视觉风格与字幕样式",
  "why_it_works": "为什么这条视频有效,可迁移的结构是什么",
  "clone_plan": [{{"start": 秒, "end": 秒, "visual": "新画面", "speech": "新台词(语言:{language})", "keep_from_reference": "沿用了原视频的什么"}}],
  "risks": ["复刻时的难点或不确定之处"]
}}
只依据拼图;看不清或看不到的写 "无法确定"。"""


def hypit(args: list[str], launcher: str) -> str:
    done = subprocess.run(["node", launcher, *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300, env={**os.environ, "NODE_USE_ENV_PROXY": "1"})
    if done.returncode != 0:
        sys.exit(f"hypit {' '.join(args[:2])} failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout


def make_sheets(video: Path, out_dir: Path, launcher: str, max_frames: int) -> tuple[float, float, list[Path]]:
    duration = float(json.loads(hypit(["media", "probe", str(video), "--json"], launcher))["duration"])
    step = max(0.5, round(duration / max_frames, 1))
    data = json.loads(hypit(["media", "tiles", str(video), "--every", str(step), "--cell", "320",
                             "--columns", "4", "--rows", "3", "--to", str(out_dir), "--json"], launcher))
    return duration, step, [Path(g["path"]) for g in data["grids"]]


def ask(provider: dict, model: str, key: str, sheets: list[Path], prompt: str, max_tokens: int,
        think: bool) -> dict:
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(p.read_bytes()).decode()}} for p in sheets]
    content.append({"type": "text", "text": prompt})
    body = {"model": model, "max_tokens": max_tokens, "system": SYSTEM,
            "messages": [{"role": "user", "content": content}]}
    if not think:  # thinking is on by default; for a structured extraction it just burns the token budget
        body["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(
        provider["base"].rstrip("/") + "/v1/messages", data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": key, "authorization": f"Bearer {key}",
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code} from {provider['base']}: {exc.read().decode('utf-8', 'replace')[:600]}")


def extract_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--provider", choices=PROVIDERS, default="deepseek")
    ap.add_argument("--model", help="override the provider's default model")
    ap.add_argument("--topic", default="程序员的一天")
    ap.add_argument("--language", default="中文")
    ap.add_argument("--max-frames", type=int, default=24, help="frames sampled across the video (12 per sheet)")
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--think", action="store_true", help="leave the model's thinking mode on (slower, costlier)")
    ap.add_argument("--launcher", default=os.environ.get("HYPIT_LAUNCHER", DEFAULT_LAUNCHER))
    ap.add_argument("--out", type=Path, default=Path("experiments/out"))
    ap.add_argument("--dry-run", action="store_true", help="only make the contact sheets; no API key, no cost")
    args = ap.parse_args()

    provider = PROVIDERS[args.provider]
    key = os.environ.get(provider["key_env"])
    if not key and not args.dry_run:
        sys.exit(f"Set the {provider['key_env']} environment variable first (the key is never read from arguments).")
    model = args.model or provider["model"]

    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / f"sheets-{time.strftime('%Y%m%d-%H%M%S')}"   # hypit creates it and refuses an existing one
    duration, step, sheets = make_sheets(args.video, work, args.launcher, args.max_frames)
    print(f"video {duration:.1f}s -> {len(sheets)} contact sheet(s), one frame every {step:g}s  ({work})")

    if args.dry_run:
        print("dry run: stopping before any API call.")
        return
    prompt = TASK.format(duration=duration, step=step, topic=args.topic, language=args.language)
    started = time.time()
    reply = ask(provider, model, key, sheets, prompt, args.max_tokens * (2 if args.think else 1), args.think)
    seconds = time.time() - started

    text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
    usage = reply.get("usage", {})
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (args.out / f"{args.provider}-{stamp}-raw.json").write_text(json.dumps(reply, ensure_ascii=False, indent=1),
                                                                 encoding="utf-8")
    raw_path = args.out / f"{args.provider}-{stamp}.txt"
    raw_path.write_text(text, encoding="utf-8")
    parsed = extract_json(text)
    if parsed is not None:
        (args.out / f"{args.provider}-{stamp}.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2),
                                                                 encoding="utf-8")

    tokens_in, tokens_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    cost = ""
    if provider["price"]:
        yuan = (tokens_in * provider["price"][0] + tokens_out * provider["price"][1]) / 1e6
        cost = f", about {yuan:.3f} yuan"
    print(f"{model}: {seconds:.0f}s, {tokens_in} in / {tokens_out} out tokens{cost}; stop={reply.get('stop_reason')}")
    print(f"blocks: {[b.get('type') for b in reply.get('content', [])]}, answer text: {len(text)} chars")
    print(f"valid JSON: {parsed is not None}  ->  {raw_path}")
    if parsed is not None:
        for key_name in ("summary", "format", "hook", "why_it_works"):
            print(f"  {key_name}: {parsed.get(key_name)}")
        print(f"  structure: {len(parsed.get('structure', []))} parts, scenes: {len(parsed.get('scenes', []))}, "
              f"clone_plan: {len(parsed.get('clone_plan', []))} parts")


if __name__ == "__main__":
    main()
