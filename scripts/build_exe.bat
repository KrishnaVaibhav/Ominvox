@echo off
REM Builds the two Windows programs:
REM   Ominvox.exe              launcher (project folder)   - opens the app window
REM   dist\OminvoxSetup.exe    installer (one file to share) - installs everything
REM Needs the setup to have been run once (uses .venv312 + the uv tool).
setlocal
set "ROOT=%~dp0..\"
cd /d "%ROOT%"
set "UV_CACHE_DIR=%ROOT%.cache\uv"
set "PYTHONIOENCODING=utf-8"
set "PY=%ROOT%.venv312\Scripts\python.exe"
set "BUILD=%ROOT%.cache\build"
set "PYI=%PY% -m PyInstaller --noconfirm --onefile --windowed --workpath %BUILD% --specpath %BUILD%"

if not exist "%PY%" (
  echo Run the setup first:  powershell -ExecutionPolicy Bypass -File setup.ps1
  exit /b 1
)

echo === Installing the build tool (PyInstaller) ===
"%ROOT%.tools\uv.exe" pip install --python "%PY%" -q -r "%ROOT%requirements-build.txt" || exit /b 1

echo === Drawing the icon ===
"%PY%" "%ROOT%installer\make_icon.py" || exit /b 1

echo === Building Ominvox.exe (launcher) ===
%PYI% --name Ominvox --icon "%ROOT%assets\ominvox.ico" --distpath "%ROOT%." ^
  "%ROOT%installer\launcher.py" || exit /b 1

if /i "%~1"=="launcher" goto :done

echo === Packing the app for the installer ===
"%PY%" "%ROOT%installer\build_payload.py" || exit /b 1

echo === Building dist\OminvoxSetup.exe (installer) ===
%PYI% --name OminvoxSetup --icon "%ROOT%assets\ominvox.ico" --distpath "%ROOT%dist" ^
  --add-data "%BUILD%\payload.zip;." --add-data "%ROOT%assets\ominvox.ico;." ^
  "%ROOT%installer\installer.py" || exit /b 1

:done
echo.
echo Built: %ROOT%Ominvox.exe
if exist "%ROOT%dist\OminvoxSetup.exe" echo Built: %ROOT%dist\OminvoxSetup.exe
endlocal
