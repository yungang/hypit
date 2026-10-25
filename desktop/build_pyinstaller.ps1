# Build a standalone Windows folder with PyInstaller (output: dist\hypit-desktop\hypit-desktop.exe).
# Setup once:  python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# This is the release build. The Nuitka build (build.ps1) currently crashes at runtime.
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Missing .venv - see the setup line at the top of this script." }
& $py -m PyInstaller run.py `
  --noconfirm --clean `
  --windowed `
  --name hypit-desktop `
  --paths . `
  --specpath build\pyinstaller `
  --workpath build\pyinstaller\work `
  --distpath dist `
  --add-data "$PSScriptRoot\hypit_desktop\agent\fixtures;hypit_desktop\agent\fixtures" `
  --add-data "$PSScriptRoot\templates;templates" `
  --add-data "$PSScriptRoot\hypit_desktop\agent\guard;hypit_desktop\agent\guard" `
  --add-data "$PSScriptRoot\..\skills\hypit;skills\hypit" `
  --collect-all claude_agent_sdk
