"""Entry point for packaging (Nuitka compiles this file).

A windowed exe has no console, so failures would be silent. Record them in
%LOCALAPPDATA%\\HypitDesktop\\crash.log and tell the user where to look."""
import faulthandler
import os
import sys
import traceback
from pathlib import Path


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "HypitDesktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run() -> int:
    log = _log_dir() / "crash.log"
    handle = open(log, "a", encoding="utf-8")
    faulthandler.enable(file=handle, all_threads=True)  # hard crashes (segfaults) leave a traceback here
    try:
        from hypit_desktop.__main__ import main
        return main()
    except BaseException:
        handle.write(traceback.format_exc() + "\n")
        handle.flush()
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"程序启动失败,详情见:\n{log}", "视频复刻助手", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(_run())
