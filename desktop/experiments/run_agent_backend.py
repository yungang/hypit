"""Run the real AI-director backend without the UI, up to the price question.

By default it answers "cancel" to the confirm card, so the only cost is the AI director's tokens (about 1 yuan);
nothing is bought from HypiHub. Add --go to approve the estimate and really generate (spends credits).

    $env:DEEPSEEK_API_KEY = "..."
    .\\.venv\\Scripts\\python.exe experiments\\run_agent_backend.py --reference D:\\path\\final.mp4 --topic "程序员的一天"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypit_desktop.agent.factory import agent_backend_from  # noqa: E402
from hypit_desktop.briefs import DEFAULTS  # noqa: E402
from hypit_desktop.settings import Settings  # noqa: E402


class ConsoleResponder:
    def __init__(self, approve: bool):
        self.approve = approve

    def wait(self, confirm_id):
        print(f"   >> 确认卡片:{'确认生成' if self.approve else '取消(未加 --go,不花生成费)'}")
        return "go" if self.approve else "cancel"

    def sleep(self, seconds):
        time.sleep(seconds)
        return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--topic", default="程序员的一天")
    ap.add_argument("--language", default="中文")
    ap.add_argument("--model", default="Seedance 2.0 Mini")
    ap.add_argument("--duration", default="15 秒")
    ap.add_argument("--resolution", default="720p")
    ap.add_argument("--task-id", type=int, default=9001)
    ap.add_argument("--data-dir", type=Path, default=Path("experiments/out/agent-backend-data"))
    ap.add_argument("--service", default="hypihub", choices=("hypihub", "ark"), help="generation service")
    ap.add_argument("--whisperx-home", default="", help="folder with the shared WhisperX .venv (ark service)")
    ap.add_argument("--feedback", default="", help="redo: what to change (same as the app's 不满意,重做)")
    ap.add_argument("--feedback-at", type=float, default=None)
    ap.add_argument("--project-from", type=int, default=None, help="redo: reuse this task's project and outputs")
    ap.add_argument("--go", action="store_true", help="approve the estimate and really generate (spends credits)")
    args = ap.parse_args()

    settings = Settings(args.data_dir / "settings.json")
    settings.set("generation_service", args.service)
    if args.whisperx_home:
        settings.set("whisperx_home", args.whisperx_home)
    backend = agent_backend_from(settings, args.data_dir)
    brief = {**DEFAULTS, "source_type": "file", "url": str(args.reference), "topic": args.topic,
             "language": args.language, "model": args.model, "duration": args.duration, "resolution": args.resolution, "task_id": args.task_id}
    if args.feedback:
        brief.update(feedback=args.feedback, feedback_at=args.feedback_at, project_from=args.project_from)
    started = time.time()
    for event in backend.run(brief, ConsoleResponder(args.go)):
        d = event.data
        text = d.get("text") or d.get("title") or d.get("prompt") or d.get("status") or d.get("path") or d.get("usd") or ""
        line = f"{time.time() - started:6.0f}s {event.type:9} {str(text)[:160]}"
        print(line.encode(sys.stdout.encoding or "utf-8", "replace").decode(sys.stdout.encoding or "utf-8", "replace"))


if __name__ == "__main__":
    main()
