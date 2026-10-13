# Build a standalone Windows folder with Nuitka (output: build\run.dist\hypit-desktop.exe).
# Setup once:  python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Needs Visual Studio's "Desktop development with C++" workload (MSVC).
# Always builds with the project's .venv: the system Python's user-site packages made Nuitka miss Qt DLLs.
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Missing .venv - see the setup line at the top of this script." }
& $py -m nuitka run.py `
  --standalone `
  --msvc=latest `
  --enable-plugin=pyside6 `
  --include-qt-plugins=multimedia `
  --windows-console-mode=disable `
  --output-filename=hypit-desktop.exe `
  --output-dir=build `
  --include-data-files="hypit_desktop/agent/fixtures/*.jsonl=hypit_desktop/agent/fixtures/" `
  --assume-yes-for-downloads
