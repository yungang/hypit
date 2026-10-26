# Build the shared local speech-alignment service (WhisperX) as one self-contained folder.
#
#   .\deploy\build_whisperx_bundle.ps1 -Target C:\HypitDesktop\services\whisperx
#
# The Python environment records absolute paths, so the folder must be installed at the SAME path it was built at.
# Pick one company-wide path (the default below), build once on a prepared machine, zip the folder, and unpack it at
# that path on every employee machine. The app finds it through Settings -> "本地语音对齐服务" (or services\whisperx
# next to the program).
#
# Needs: uv, Python 3.13 (uv fetches it), a Hypit checkout or an npm install of @hypit/provider-whisperx-local, and a
# machine where the models are already downloaded (hf cache: faster-whisper small + the zh alignment model; torch cache:
# the English alignment checkpoint; NLTK punkt_tab). The finished folder is about 2.5 GB.
param(
  [string]$Target = "C:\HypitDesktop\services\whisperx",
  [string]$RuntimeProject = (Join-Path $PSScriptRoot "..\..\packages\provider-whisperx-local\runtime"),
  [string]$HfHub = (Join-Path $env:USERPROFILE ".cache\huggingface\hub"),
  [string]$TorchCheckpoints = (Join-Path $env:USERPROFILE ".cache\torch\hub\checkpoints"),
  [string]$NltkData = "",
  [string]$AppPython = (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe")
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is not installed (winget install astral-sh.uv)." }
if (-not (Test-Path (Join-Path $RuntimeProject "pyproject.toml"))) { throw "RuntimeProject not found: $RuntimeProject" }
if ($NltkData -eq "" -or -not (Test-Path $NltkData)) { throw "Pass -NltkData <folder that holds tokenizers\punkt_tab>." }

$models = @("models--Systran--faster-whisper-small", "models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn")
foreach ($m in $models) { if (-not (Test-Path (Join-Path $HfHub $m))) { throw "Model missing in the Hugging Face cache: $m" } }
$english = Join-Path $TorchCheckpoints "wav2vec2_fairseq_base_ls960_asr_ls960.pth"
if (-not (Test-Path $english)) { throw "English alignment checkpoint missing: $english" }
if ((Get-Item $english).Length -lt 300MB) { throw "English alignment checkpoint looks truncated ($((Get-Item $english).Length) bytes)." }

New-Item -ItemType Directory -Force $Target | Out-Null
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Target "python"      # the interpreter lives inside the bundle
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Target ".venv"
$env:UV_HTTP_TIMEOUT = "600"
Write-Host "1/4 Python environment..."
uv sync --project $RuntimeProject --frozen --no-editable
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

Write-Host "2/4 Sentence data and models..."
robocopy $NltkData (Join-Path $Target "nltk_data") /E /NFL /NDL /NJH /NJS | Out-Null
foreach ($m in $models) {
  # snapshots hold real files on Windows, so the duplicate 'blobs' folder is left out (saves about 1.7 GB)
  robocopy (Join-Path $HfHub $m) (Join-Path $Target "models\huggingface\$m") /E /XD blobs .no_exist /NFL /NDL /NJH /NJS | Out-Null
}
# the service reads these two folders directly: models\huggingface\models--*  and  models\torch\*.pth
New-Item -ItemType Directory -Force (Join-Path $Target "models\torch") | Out-Null
Copy-Item $english (Join-Path $Target "models\torch") -Force

Write-Host "3/4 Start script..."
& $AppPython -m hypit_desktop.agent.whisperx $Target
if ($LASTEXITCODE -ne 0) { throw "could not write start-whisperx.cmd" }

Write-Host "4/4 Checking that every model loads from the bundle (offline)..."
$env:HYPIT_WHISPERX_NLTK_DATA = Join-Path $Target "nltk_data"
$env:HYPIT_WHISPERX_MODEL_CACHE = Join-Path $Target "models"
$env:HYPIT_WHISPERX_ALIGNMENT_LANGUAGES = "zh en"
$env:HF_HUB_OFFLINE = "1"
& (Join-Path $Target ".venv\Scripts\hypit-whisperx-check.exe") --models
if ($LASTEXITCODE -ne 0) { throw "the bundle check failed" }
$size = [int]((Get-ChildItem $Target -Recurse -File -Force | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Done: $Target ($size MB). Zip it and unpack at the same path on each machine."
