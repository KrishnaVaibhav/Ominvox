# Builds Ominvox.exe (launcher) and dist\OminvoxSetup.exe (installer) with any
# Python 3.12 - used by GitHub Actions (CI and releases). On your own PC,
# scripts\build_exe.bat does the same with the project's .venv312.
#
#   powershell -File scripts\build_release.ps1 [-Python path\to\python.exe] [-NoInstall]
# -NoInstall skips "pip install" (for a venv that already has PyInstaller + Pillow).
param([string]$Python = "python", [switch]$NoInstall)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$build = Join-Path $root ".cache\build"
$icon = Join-Path $root "assets\ominvox.ico"
$pyi = @("-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
         "--workpath", $build, "--specpath", $build)

function Run([string[]]$cmd) {
    & $Python @cmd
    if ($LASTEXITCODE -ne 0) { throw "failed: python $($cmd -join ' ')" }
}

if (-not $NoInstall) {
    Write-Host "=== Installing the build tools ==="
    Run @("-m", "pip", "install", "-q", "-r", "requirements-build.txt")
}
Write-Host "=== Drawing the icon ==="
Run @("installer\make_icon.py")
Write-Host "=== Building Ominvox.exe (launcher) ==="
Run ($pyi + @("--name", "Ominvox", "--icon", $icon, "--distpath", $root, "installer\launcher.py"))
Write-Host "=== Packing the app for the installer ==="
Run @("installer\build_payload.py")
Write-Host "=== Building dist\OminvoxSetup.exe (installer) ==="
Run ($pyi + @("--name", "OminvoxSetup", "--icon", $icon, "--distpath", (Join-Path $root "dist"),
              "--add-data", "$build\payload.zip;.", "--add-data", "$icon;.", "installer\installer.py"))

foreach ($f in @("Ominvox.exe", "dist\OminvoxSetup.exe")) {
    $item = Get-Item $f
    if ($item.Length -lt 1MB) { throw "$f looks broken ($($item.Length) bytes)" }
    Write-Host ("Built {0} ({1:N1} MB)" -f $f, ($item.Length / 1MB))
}
