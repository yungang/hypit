"""Second validation: can a cheap model run a tool loop the way a Hypit agent has to?

The model starts blind (no frames). It must call `media_probe` and `look` (which runs `hypit media tile`)
by itself, decide which moments to inspect, recover from a bad call, and finish with a JSON analysis.
That exercises: valid tool arguments, multi-step planning, images coming back from tools, stopping.

    python experiments/agent_tools_probe.py D:\\path\\video.mp4 --provider deepseek --think

Keys come from environment variables only. Standard library only. Cost: well under 1 yuan."""
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

sys.path.insert(0, str(Path(__file__).parent))
from analyze_reference import DEFAULT_LAUNCHER, PROVIDERS, extract_json  # noqa: E402

SYSTEM_TEMPLATE = """你是短视频复刻导演,正在为一条参考视频做分析。你现在什么画面都还没看到,必须自己用工具去看,不要凭空描述。
工作方式:
1. 先用 media_probe 了解时长和规格。
2. 用 look 看画面。每次最多 12 个时间点,会得到一张拼图(格子下方是时间戳,画面里有烧录字幕)。
   你总共只有 {max_looks} 次 look 机会:先均匀粗看一遍,再把剩下的次数集中用在你最不确定的地方
   (镜头切换点、台词、版面布局),每次都要把 12 个格子用满。工具结果会告诉你还剩几次。
3. 次数用完、或者你已经看够了,就必须回答。最后一条消息只输出一个 JSON,不要有别的文字。字段:
   summary, format, structure[{start,end,purpose}], cuts[切镜头的准确时间点,秒], people[{role,look}],
   speech[{start,end,text}], why_it_works, evidence[你看了哪些时间点,以及它们支持了什么结论]。
所有时间都必须来自你看过的画面;看不清就写"无法确定"。"""

TOOLS = [
    {"name": "media_probe", "description": "读取视频的时长、分辨率、帧率、是否有音频。无参数。",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "look", "description": "抽取指定时间点的画面,拼成一张带时间戳的图返回。一次 1 到 12 个时间点,单位秒,必须在视频时长内。",
     "input_schema": {"type": "object",
                      "properties": {"times": {"type": "array", "items": {"type": "number"},
                                               "description": "要查看的时间点(秒)"}},
                      "required": ["times"]}},
]


class Tools:
    def __init__(self, video: Path, launcher: str, work: Path):
        self.video, self.launcher, self.work = video, launcher, work
        self.duration = 0.0
        self.looked: list[float] = []
        self.looks: list[int] = []      # one entry per look call
        self.max_looks = 6
        self.calls = 0
        self.errors = 0

    def _hypit(self, args: list[str]) -> str:
        done = subprocess.run(["node", self.launcher, *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300, env={**os.environ, "NODE_USE_ENV_PROXY": "1"})
        if done.returncode != 0:
            raise RuntimeError((done.stdout + done.stderr).strip()[-400:])
        return done.stdout

    def run(self, name: str, args: dict) -> tuple[str, list[Path], bool]:
        """Return (text, images, is_error)."""
        self.calls += 1
        try:
            if name == "media_probe":
                info = json.loads(self._hypit(["media", "probe", str(self.video), "--json"]))
                self.duration = float(info["duration"])
                return json.dumps({k: info[k] for k in ("duration", "width", "height", "frameRate", "hasAudio")}), [], False
            if name == "look":
                times = args.get("times")
                if not isinstance(times, list) or not 1 <= len(times) <= 12:
                    raise ValueError("times 必须是 1 到 12 个数字组成的数组")
                last_frame = max(0.0, (self.duration or 1e9) - 0.1)   # no frame exists at the very end
                times = sorted({round(min(max(float(t), 0.0), last_frame), 2) for t in times})
                target = self.work / f"look-{self.calls:02d}.jpg"
                self._hypit(["media", "tile", str(self.video), "--at", ",".join(f"{t:g}" for t in times),
                             "--cell", "360", "--columns", "4", "--to", str(target)])
                self.looked.extend(times)
                self.looks.append(len(times))
                left = self.max_looks - sum(1 for _ in self.looks)
                return (f"这张图按从左到右、从上到下的顺序依次是 {', '.join(f'{t:g}s' for t in times)}"
                        f"(已自动排序、去重、限制在视频时长内)。你还剩 {left} 次 look。"), [target], False
            raise ValueError(f"没有这个工具:{name}")
        except (ValueError, RuntimeError, KeyError) as exc:
            self.errors += 1
            return f"工具出错:{exc}", [], True


def image_block(path: Path) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(path.read_bytes()).decode()}}


def call(provider: dict, model: str, key: str, messages: list, think: bool, max_tokens: int,
         system: str, force_answer: bool) -> dict:
    body = {"model": model, "max_tokens": max_tokens, "system": system, "tools": TOOLS, "messages": messages}
    if force_answer:
        body["tool_choice"] = {"type": "none"}
    if not think:
        body["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(
        provider["base"].rstrip("/") + "/v1/messages", data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": key, "authorization": f"Bearer {key}",
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code, "body": exc.read().decode("utf-8", "replace")[:800]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--provider", choices=PROVIDERS, default="deepseek")
    ap.add_argument("--model")
    ap.add_argument("--think", action="store_true")
    ap.add_argument("--max-steps", type=int, default=10)
    ap.add_argument("--max-looks", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--images-in-user", action="store_true",
                    help="return tool images in a follow-up user message instead of inside tool_result")
    ap.add_argument("--launcher", default=os.environ.get("HYPIT_LAUNCHER", DEFAULT_LAUNCHER))
    ap.add_argument("--out", type=Path, default=Path("experiments/out"))
    args = ap.parse_args()

    provider = PROVIDERS[args.provider]
    key = os.environ.get(provider["key_env"])
    if not key:
        sys.exit(f"Set the {provider['key_env']} environment variable first.")
    model = args.model or provider["model"]
    work = args.out / f"agent-{time.strftime('%Y%m%d-%H%M%S')}"
    work.mkdir(parents=True)
    tools = Tools(args.video, args.launcher, work)
    tools.max_looks = args.max_looks
    system = SYSTEM_TEMPLATE.replace("{max_looks}", str(args.max_looks))   # the prompt has literal braces
    log = (work / "transcript.jsonl").open("w", encoding="utf-8")

    messages = [{"role": "user", "content": "请分析这条参考视频(路径已由工具内部固定,不需要你提供)。开始吧。"}]
    totals = {"in": 0, "cached": 0, "out": 0}
    started, final_text, stop = time.time(), "", ""
    for step in range(1, args.max_steps + 1):
        force = len(tools.looks) >= args.max_looks or step >= args.max_steps
        reply = call(provider, model, key, messages, args.think, args.max_tokens * (2 if args.think else 1),
                     system, force)
        if "http_error" in reply:
            log.write(json.dumps({"step": step, "error": reply}, ensure_ascii=False) + "\n")
            sys.exit(f"HTTP {reply['http_error']}: {reply['body']}")
        usage = reply.get("usage", {})
        totals["in"] += usage.get("input_tokens", 0)
        totals["cached"] += usage.get("cache_read_input_tokens", 0)
        totals["out"] += usage.get("output_tokens", 0)
        content = reply.get("content", [])
        log.write(json.dumps({"step": step, "stop": reply.get("stop_reason"), "usage": usage,
                              "content": [{k: v for k, v in b.items() if k != "signature"} for b in content]},
                             ensure_ascii=False) + "\n")
        messages.append({"role": "assistant", "content": content})
        uses = [b for b in content if b.get("type") == "tool_use"]
        stop = reply.get("stop_reason", "")
        if not uses:
            final_text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            break
        results, extra_images = [], []
        for use in uses:
            text, images, is_error = tools.run(use["name"], use.get("input") or {})
            print(f"step {step}: {use['name']}({json.dumps(use.get('input'), ensure_ascii=False)})"
                  f"{'  ERROR' if is_error else ''}")
            if args.images_in_user:
                results.append({"type": "tool_result", "tool_use_id": use["id"], "content": text, "is_error": is_error})
                extra_images += [image_block(p) for p in images]
            else:
                body = [image_block(p) for p in images] + [{"type": "text", "text": text}]
                results.append({"type": "tool_result", "tool_use_id": use["id"], "content": body, "is_error": is_error})
        nudge = []
        if len(tools.looks) >= args.max_looks or step + 1 >= args.max_steps:
            nudge = [{"type": "text", "text": "看画面的机会已用完。请现在只输出最终的 JSON 分析。"}]
        messages.append({"role": "user", "content": results + extra_images + nudge})

    seconds = time.time() - started
    parsed = extract_json(final_text)
    (work / "final.txt").write_text(final_text, encoding="utf-8")
    if parsed is not None:
        (work / "final.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    price = provider["price"]
    cost = ""
    if price:
        yuan = (totals["in"] * price[0] + totals["cached"] * 0.04 + totals["out"] * price[1]) / 1e6
        cost = f", about {yuan:.3f} yuan"
    print(f"\n{model} think={args.think}: {seconds:.0f}s, {totals['in']}+{totals['cached']}(cached) in / "
          f"{totals['out']} out tokens{cost}")
    print(f"tool calls: {tools.calls}, tool errors: {tools.errors}, distinct moments looked at: "
          f"{len(set(tools.looked))}, stop: {stop}")
    print(f"final answer: {len(final_text)} chars, valid JSON: {parsed is not None}  ->  {work}")
    if parsed is not None:
        print(f"  cuts reported: {parsed.get('cuts')}")
        print(f"  summary: {parsed.get('summary')}")


if __name__ == "__main__":
    main()
