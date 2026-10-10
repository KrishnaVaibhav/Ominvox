# ===== Ominvox setup. Everything (Python, libraries, caches) stays in this folder. =====
# Builds a Python 3.12 environment in .venv312 with the portable "uv" tool, which
# downloads a standalone CPython into .cache\python. Nothing is installed system-wide.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1 [-NoShortcut]
#
# Progress lines look like "=== [n/6] ... ===" (OminvoxSetup.exe reads them).
# The AI models are NOT downloaded here: the app's first-run screen does that,
# with progress bars.
param([switch]$NoShortcut)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# --- every cache (incl. TMP) inside the project ---
$cache = Join-Path $root ".cache"
$env:UV_CACHE_DIR          = Join-Path $cache "uv"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $cache "python"
$env:HF_HOME               = Join-Path $cache "huggingface"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $cache "huggingface\hub"
$env:TORCH_HOME            = Join-Path $cache "torch"
$env:TTS_HOME              = Join-Path $cache "tts"
$env:XDG_CACHE_HOME        = $cache
$env:TMP                   = Join-Path $cache "tmp"
$env:TEMP                  = $env:TMP
$env:PYTHONIOENCODING      = "utf-8"
foreach ($d in @($cache, $env:TMP, (Join-Path $cache "speakers"))) {
  New-Item -ItemType Directory -Force $d | Out-Null
}

$uv     = Join-Path $root ".tools\uv.exe"
$venvPy = Join-Path $root ".venv312\Scripts\python.exe"
$steps  = 6

function Step([int]$n, [string]$title) { Write-Output "`n=== [$n/$steps] $title ===" }

# Native commands run through cmd with stderr merged: Windows PowerShell 5.1 turns
# stderr text (progress, harmless warnings) into terminating errors otherwise,
# especially when this script's output is captured by the installer.
function Invoke-Native([string]$CommandLine, [string]$What) {
  & cmd /s /c "`"$CommandLine 2>&1`"" | ForEach-Object { Write-Output "  $_" }
  if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

# 1 ── portable uv (gitignored, so fetched on first run) ───────────────────
Step 1 "Getting the installer tool (uv)"
if (-not (Test-Path $uv)) {
  $tools = Join-Path $root ".tools"
  $zip   = Join-Path $env:TMP "uv.zip"
  New-Item -ItemType Directory -Force $tools | Out-Null
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $ProgressPreference = "SilentlyContinue"          # makes Invoke-WebRequest much faster
  Invoke-WebRequest -UseBasicParsing -OutFile $zip `
    -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
  Expand-Archive -Path $zip -DestinationPath $tools -Force
  Remove-Item $zip -Force
  if (-not (Test-Path $uv)) {
    throw "Could not get uv.exe. Download uv-x86_64-pc-windows-msvc.zip from https://github.com/astral-sh/uv/releases/latest and put uv.exe in $tools"
  }
}
Invoke-Native "`"$uv`" --version" "uv"

# 2 ── Python 3.12 environment ──────────────────────────────────────────────
Step 2 "Installing Python 3.12"
Invoke-Native "`"$uv`" venv --allow-existing --python 3.12 `"$(Join-Path $root '.venv312')`"" "Creating the Python environment"

# 3 ── libraries ────────────────────────────────────────────────────────────
Step 3 "Installing the AI libraries (largest step)"
Invoke-Native "`"$uv`" pip install --python `"$venvPy`" -r `"$(Join-Path $root 'requirements.txt')`"" "Installing the libraries"

# 4 ── GPU PyTorch, installed LAST so nothing replaces it with a CPU build ───
# Note: pyannote.audio 4 declares torch>=2.8, but 2.6+cu124 runs it fine (all
# tests pass) and works with older NVIDIA drivers. Change cu124 here if needed.
Step 4 "Installing GPU support (PyTorch CUDA 12.4)"
Invoke-Native "`"$uv`" pip install --python `"$venvPy`" --reinstall torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124" "Installing GPU PyTorch"

# 5 ── self-test ────────────────────────────────────────────────────────────
Step 5 "Checking the installation"
Invoke-Native "`"$venvPy`" -m ominvox.app --check" "Self-test"

# 6 ── launcher + shortcut ──────────────────────────────────────────────────
Step 6 "Creating the Ominvox launcher"
$exe = Join-Path $root "Ominvox.exe"
if (-not (Test-Path $exe)) {
  try { Invoke-Native "`"$(Join-Path $root 'scripts\build_exe.bat')`" launcher" "Building Ominvox.exe" }
  catch { Write-Output "  (Ominvox.exe could not be built - start_ui.bat still works: $_)" }
}
if ((Test-Path $exe) -and -not $NoShortcut) {
  try {
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Ominvox.lnk"
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sh.TargetPath = $exe; $sh.WorkingDirectory = $root
    $sh.IconLocation = "$exe,0"; $sh.Description = "Ominvox - live movie translation"
    $sh.Save()
    Write-Output "  Desktop shortcut: $lnk"
  } catch { Write-Output "  (Could not create a desktop shortcut: $_)" }
}

Write-Output "`n===== SETUP COMPLETE ====="
Write-Output "Start Ominvox with the desktop shortcut, Ominvox.exe, or start_ui.bat."
Write-Output "On first start it checks your PC and downloads the AI models (with progress)."
