"""Test guard that stands in for the `hypit` command inside an agent test workspace.

Read-only and planning commands pass through to the real Hypit CLI. Anything that spends money, logs in,
downloads, or changes the machine is refused with an explanation, so the model can report what it *would*
run. Every call is appended to guard.log next to the workspace."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

LAUNCHER = os.environ.get("HYPIT_LAUNCHER", r"D:\Dev\hypit-runtime\node_modules\@hypit\hypit\bin\hypit.mjs")
ALLOWED = {"version", "paths", "check", "plan", "pricing", "doctor", "vocabulary", "media", "estimate",
           "builds", "history", "inspect", "status", "logs", "get", "help", "--help", "-h", "--version", "-v"}
ALLOWED_SUB = {"runtime": {"init", "use", "status", "unset"}, "programs": {"status"}, "cli": {"status"}}
WHY = {
    "build": "submits a paid Build",
    "auth": "logs in or out of a service",
    "download": "fetches a network video / installs a downloader",
    "transcribe": "calls a paid hosted speech service",
    "cancel": "controls a running Build",
    "capture": "installs or runs a browser",
}


def log(entry: dict, workspace: Path) -> None:
    entry["time"] = time.strftime("%H:%M:%S")
    with (workspace / "guard.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    argv = sys.argv[1:]
    workspace = Path(os.environ.get("HYPIT_GUARD_WORKSPACE", Path.cwd()))
    command = argv[0] if argv else "help"
    sub = argv[1] if len(argv) > 1 else ""
    allowed = command in ALLOWED or (command in ALLOWED_SUB and sub in ALLOWED_SUB[command])
    log({"argv": argv, "allowed": allowed}, workspace)
    if not allowed:
        reason = WHY.get(command, "is not part of this read-only test")
        print(f"BLOCKED by the test guard: `hypit {' '.join(argv)}` {reason}. "
              "Do not retry it. Stop here and report the command you would have run and why.", file=sys.stderr)
        return 3
    done = subprocess.run(["node", LAUNCHER, *argv], env={**os.environ, "NODE_USE_ENV_PROXY": "1"})
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
