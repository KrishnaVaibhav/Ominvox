@echo off
REM Runs Ominvox from the project-local Python 3.12 venv (.venv312, built by setup.ps1).
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "HF_HOME=%ROOT%.cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%ROOT%.cache\huggingface\hub"
set "TORCH_HOME=%ROOT%.cache\torch"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"
set "PYTHONIOENCODING=utf-8"
if not exist "%ROOT%.venv312\Scripts\python.exe" (
  echo.
  echo  Ominvox is not installed yet.
  echo  Run the setup first ^(see README section 2^):
  echo      powershell -ExecutionPolicy Bypass -File setup.ps1
  echo.
  exit /b 1
)
"%ROOT%.venv312\Scripts\python.exe" -m ominvox.app %*
