# ===== Ominvox setup via portable uv. Env + ALL caches stay in this folder. =====
# Builds a Python 3.12 venv at .venv312 using a standalone CPython that uv
# downloads INTO the project (.cache\python). Nothing new is written to C:.
$ErrorActionPreference = "Stop"
$root = (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

# --- pin every cache (incl. TMP) inside the project: zero new C: footprint ---
$cache = Join-Path $root ".cache"
$env:UV_CACHE_DIR            = Join-Path $cache "uv"
$env:UV_PYTHON_INSTALL_DIR   = Join-Path $cache "python"     # standalone CPython lands here
$env:HF_HOME                 = Join-Path $cache "huggingface"
$env:HUGGINGFACE_HUB_CACHE   = Join-Path $cache "huggingface\hub"
$env:TORCH_HOME              = Join-Path $cache "torch"
$env:PIP_CACHE_DIR           = Join-Path $cache "pip"
$env:TTS_HOME                = Join-Path $cache "tts"
$env:XDG_CACHE_HOME          = $cache
$env:TMP                     = Join-Path $cache "tmp"
$env:TEMP                    = Join-Path $cache "tmp"
foreach ($d in @($cache, $env:TMP, (Join-Path $cache "speakers"))) {
  New-Item -ItemType Directory -Force $d | Out-Null
}

$uv     = Join-Path $root ".tools\uv.exe"
$venv   = Join-Path $root ".venv312"
$venvPy = Join-Path $venv "Scripts\python.exe"

# --- fetch the portable uv into .tools if it isn't there yet (it's gitignored) ---
if (-not (Test-Path $uv)) {
  $tools = Join-Path $root ".tools"
  $zip   = Join-Path $env:TMP "uv.zip"
  $url   = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
  Write-Output "=== uv.exe not found - downloading it into .tools ==="
  New-Item -ItemType Directory -Force $tools | Out-Null
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
  Expand-Archive -Path $zip -DestinationPath $tools -Force
  Remove-Item $zip -Force
  if (-not (Test-Path $uv)) {
    throw "Could not get uv.exe. Download uv-x86_64-pc-windows-msvc.zip from https://github.com/astral-sh/uv/releases/latest and put uv.exe in $tools"
  }
}

Write-Output "=== uv: $uv ==="
& $uv --version

Write-Output "`n=== Create Python 3.12 venv at $venv (uv fetches standalone CPython into .cache\python) ==="
& $uv venv --python 3.12 $venv
if ($LASTEXITCODE -ne 0) { throw "uv venv failed ($LASTEXITCODE)" }

Write-Output "`n=== Core requirements (no torch yet) ==="
& $uv pip install --python $venvPy -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "core requirements install failed ($LASTEXITCODE)" }

Write-Output "`n=== coqui-tts (pulls a CPU torch; replaced below) ==="
& $uv pip install --python $venvPy coqui-tts
if ($LASTEXITCODE -ne 0) { throw "coqui-tts install failed ($LASTEXITCODE)" }

Write-Output "`n=== GPU PyTorch LAST so it wins (CUDA 12.4). Edit cu124 if driver differs. ==="
& $uv pip install --python $venvPy --reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu124
if ($LASTEXITCODE -ne 0) { throw "CUDA torch install failed ($LASTEXITCODE)" }

Write-Output "`n=== Dependency self-test -> check_output.txt ==="
# Route through cmd: PowerShell 5.1 + ErrorActionPreference=Stop would otherwise turn
# pyannote's harmless torchcodec stderr warning into a NativeCommandError and abort.
$chk = Join-Path $root "check_output.txt"
& cmd /c "`"$venvPy`" -m ominvox.app --check > `"$chk`" 2>&1"
$checkExit = $LASTEXITCODE
Get-Content $chk

if ($checkExit -ne 0) { throw "Self-test failed (exit $checkExit) - see check_output.txt" }

Write-Output "`n=== Building Ominvox.exe (double-click launcher) ==="
# stderr merged inside cmd for the same PowerShell 5.1 reason as the self-test above
try { & cmd /c "`"$(Join-Path $root 'build_exe.bat')`" 2>&1" } catch { Write-Output "(build failed: $_)" }
$exe = Join-Path $root "Ominvox.exe"
if (Test-Path $exe) {
  try {
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Ominvox.lnk"
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sh.TargetPath = $exe; $sh.WorkingDirectory = $root
    $sh.IconLocation = "$exe,0"; $sh.Description = "Ominvox - live movie translation"
    $sh.Save()
    Write-Output "Desktop shortcut created: $lnk"
  } catch { Write-Output "(Could not create a desktop shortcut: $_)" }
} else {
  Write-Output "(Ominvox.exe was not built - you can still use start_ui.bat)"
}

Write-Output "`n===== SETUP COMPLETE (self-test exit code: $checkExit) ====="
Write-Output "Start Ominvox with the desktop shortcut, Ominvox.exe, or start_ui.bat."
