@echo off
REM Builds Ominvox.exe (the double-click launcher) into this folder.
REM Needs the setup to have been run once (uses .venv312 + the uv tool).
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "UV_CACHE_DIR=%ROOT%.cache\uv"
set "PYTHONIOENCODING=utf-8"
set "PY=%ROOT%.venv312\Scripts\python.exe"

if not exist "%PY%" (
  echo Run the setup first:  powershell -ExecutionPolicy Bypass -File setup_uv.ps1
  exit /b 1
)

echo === Installing the build tool (PyInstaller) ===
"%ROOT%.tools\uv.exe" pip install --python "%PY%" -q -r "%ROOT%requirements-build.txt" || exit /b 1

echo === Drawing the icon ===ofcourse
"%PY%" "%ROOT%launcher\make_icon.py" || exit /b 1

echo === Building Ominvox.exe ===
"%PY%" -m PyInstaller --noconfirm --onefile --windowed --name Ominvox ^
  --icon "%ROOT%assets\ominvox.ico" ^
  --distpath "%ROOT%." --workpath "%ROOT%.cache\build" --specpath "%ROOT%.cache\build" ^
  "%ROOT%launcher\ominvox_launcher.py" || exit /b 1

echo.
echo Built: %ROOT%Ominvox.exe
endlocal
