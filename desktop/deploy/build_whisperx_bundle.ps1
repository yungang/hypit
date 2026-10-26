# Build the shared local speech-alignment service (WhisperX) as one self-contained, relocatable folder.
#
#   .\deploy\build_whisperx_bundle.ps1                      # builds into dist\hypit-desktop\services\whisperx
#   .\deploy\build_whisperx_bundle.ps1 -Target D:\x\whisperx
#
# The folder carries its own Python interpreter, packages, models and sentence data, and its start script runs that
# interpreter directly, so the folder can be unpacked ANYWHERE. The app looks for it at services\whisperx next to
# hypit-desktop.exe (or wherever Settings -> "本地语音对齐服务" points). Run build_pyinstaller.ps1 first: it recreates
# dist\hypit-desktop and would delete a bundle built there earlier.
#
# Needs: uv, a Hypit checkout or an npm install of @hypit/provider-whisperx-local, and a machine where the models are
# already downloaded (hf cache: faster-whisper small + the zh alignment model; torch cache: the English alignment
# checkpoint). Sentence data (punkt_tab) is found automatically or downloaded. The finished folder is about 3.9 GB.
# Zip it with `tar -a -c -f whisperx.zip whisperx` (Compress-Archive in Windows PowerShell stops at 2 GB).
param(
  [string]$Target = (Join-Path $PSScriptRoot "..\dist\hypit-desktop\services\whisperx"),
  [string]$RuntimeProject = (Join-Path $PSScriptRoot "..\..\packages\provider-whisperx-local\runtime"),
  [string]$HfHub = (Join-Path $env:USERPROFILE ".cache\huggingface\hub"),
  [string]$TorchCheckpoints = (Join-Path $env:USERPROFILE ".cache\torch\hub\checkpoints"),
  [string]$NltkData = "",
  [switch]$TrustProxy,       # let NLTK download through your proxy (it refuses by default); only if you trust that proxy
  [string]$AppPython = (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe")
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is not installed (winget install astral-sh.uv)." }
if (-not (Test-Path (Join-Path $RuntimeProject "pyproject.toml"))) { throw "RuntimeProject not found: $RuntimeProject" }
$Target = [System.IO.Path]::GetFullPath($Target)

# NLTK sentence data (tokenizers\punkt_tab): the given folder, an earlier bundle, a Hypit-managed install or NLTK's own
# default places. When none has it, it is downloaded into the bundle after the Python environment exists.
function Find-NltkData([string]$Given) {
  $candidates = @($Given, (Join-Path $Target "nltk_data"), (Join-Path $env:APPDATA "nltk_data"), (Join-Path $env:USERPROFILE "nltk_data"))
  $candidates += Get-ChildItem (Join-Path $env:LOCALAPPDATA "Hypit\programs") -Directory -Filter "whisperx-*" -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "nltk_data" }
  foreach ($c in $candidates) { if ($c -and (Test-Path (Join-Path $c "tokenizers\punkt_tab"))) { return $c } }
  return ""
}
if ($NltkData -ne "" -and -not (Test-Path (Join-Path $NltkData "tokenizers\punkt_tab"))) {
  throw "-NltkData $NltkData has no tokenizers\punkt_tab inside."
}

$models = @("models--Systran--faster-whisper-small", "models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn")
foreach ($m in $models) { if (-not (Test-Path (Join-Path $HfHub $m))) { throw "Model missing in the Hugging Face cache: $m" } }
$english = Join-Path $TorchCheckpoints "wav2vec2_fairseq_base_ls960_asr_ls960.pth"
if (-not (Test-Path $english)) { throw "English alignment checkpoint missing: $english" }
if ((Get-Item $english).Length -lt 300MB) { throw "English alignment checkpoint looks truncated ($((Get-Item $english).Length) bytes)." }

New-Item -ItemType Directory -Force $Target | Out-Null
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Target "python"      # ask uv to keep the interpreter inside the bundle
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Target ".venv"
$env:UV_HTTP_TIMEOUT = "600"
Write-Host "1/4 Python environment..."
uv sync --project $RuntimeProject --frozen --no-editable
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

# The interpreter must live inside the bundle. uv may have reused one it already had elsewhere: copy that one in.
$pythonRoot = Join-Path $Target "python"
function Get-BundledPython {
  Get-ChildItem $pythonRoot -Directory -Filter "cpython-*" -ErrorAction SilentlyContinue |
    Where-Object { -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -and (Test-Path (Join-Path $_.FullName "python.exe")) } |
    Select-Object -First 1
}
if (-not (Get-BundledPython)) {
  $base = ((Get-Content (Join-Path $Target ".venv\pyvenv.cfg")) | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', ''
  if ((Split-Path $base -Leaf) -notlike "cpython-*") {
    throw "The environment uses $base, which is not a uv standalone Python and cannot be copied. Remove $Target\.venv and run again."
  }
  Write-Host "    copying the interpreter ($base) into the bundle..."
  robocopy $base (Join-Path $pythonRoot (Split-Path $base -Leaf)) /E /NFL /NDL /NJH /NJS | Out-Null
}
# uv leaves a minor-version junction that points at an absolute path; the bundle does not use it
Get-ChildItem $pythonRoot -Directory | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
  ForEach-Object { cmd /c rmdir "$($_.FullName)" }
$found = Get-BundledPython
if (-not $found) { throw "no interpreter inside $pythonRoot" }
$bundledPython = Join-Path $found.FullName "python.exe"
$env:HYPIT_SITE_PACKAGES = Join-Path $Target ".venv\Lib\site-packages"     # how the start script reaches the packages
$env:PYTHONNOUSERSITE = "1"

Write-Host "2/4 Sentence data and models..."
$nltkTarget = Join-Path $Target "nltk_data"
$nltkSource = Find-NltkData $NltkData
if ($nltkSource -ne "") {
  Write-Host "    sentence data from $nltkSource"
  if ((Resolve-Path $nltkSource).Path -ne (Resolve-Path $nltkTarget -ErrorAction SilentlyContinue).Path) {
    robocopy $nltkSource $nltkTarget /E /NFL /NDL /NJH /NJS | Out-Null
  }
} else {
  Write-Host "    no sentence data found, downloading punkt_tab..."
  if ($TrustProxy) { $env:NLTK_ALLOW_PROXIED_URLOPEN = "1" }          # this download only; removed again below
  & $bundledPython -c "import os, site, sys; site.addsitedir(os.environ['HYPIT_SITE_PACKAGES']); import nltk; sys.exit(0 if nltk.download('punkt_tab', download_dir=sys.argv[1], quiet=True) else 1)" $nltkTarget 2>&1 | Out-Null
  $downloaded = $LASTEXITCODE
  Remove-Item Env:NLTK_ALLOW_PROXIED_URLOPEN -ErrorAction SilentlyContinue
  if ($downloaded -ne 0) {
    throw ("Could not download punkt_tab. Either pass -NltkData <folder that holds tokenizers\punkt_tab> " +
           "(a folder from an earlier bundle works), or add -TrustProxy if you use a proxy you trust " +
           "(NLTK refuses to download through a proxy otherwise).")
  }
}
foreach ($m in $models) {
  # snapshots hold real files on Windows, so the duplicate 'blobs' folder is left out (saves about 1.7 GB)
  robocopy (Join-Path $HfHub $m) (Join-Path $Target "models\huggingface\$m") /E /XD blobs .no_exist /NFL /NDL /NJH /NJS | Out-Null
}
# the service reads these two folders directly: models\huggingface\models--*  and  models\torch\*.pth
New-Item -ItemType Directory -Force (Join-Path $Target "models\torch") | Out-Null
Copy-Item $english (Join-Path $Target "models\torch") -Force

Write-Host "3/4 Start script..."
$env:PYTHONPATH = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path     # so this works from any folder
& $AppPython -m hypit_desktop.agent.whisperx $Target
if ($LASTEXITCODE -ne 0) { throw "could not write start-whisperx.cmd" }
Remove-Item Env:PYTHONPATH

Write-Host "4/4 Checking the bundle the way the start script runs it (bundled interpreter, offline)..."
$env:HYPIT_WHISPERX_NLTK_DATA = $nltkTarget
$env:HYPIT_WHISPERX_MODEL_CACHE = Join-Path $Target "models"
$env:HYPIT_WHISPERX_ALIGNMENT_LANGUAGES = "zh en"
$env:HF_HUB_OFFLINE = "1"
& $bundledPython -c "import os, site, sys; site.addsitedir(os.environ['HYPIT_SITE_PACKAGES']); sys.argv = ['check', '--models']; from hypit_whisperx_service.check import main; sys.exit(main())"
if ($LASTEXITCODE -ne 0) { throw "the bundle check failed" }
$size = [int]((Get-ChildItem $Target -Recurse -File -Force | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Done: $Target ($size MB). Unpack it as services\whisperx next to hypit-desktop.exe (any location works)."
