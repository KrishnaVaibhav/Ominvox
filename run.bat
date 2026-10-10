@echo off
REM Runs Ominvox from the project-local Python 3.12 venv (.venv312, built by setup_uv.ps1).
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "HF_HOME=%ROOT%.cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%ROOT%.cache\huggingface\hub"
set "TORCH_HOME=%ROOT%.cache\torch"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"
set "COQUI_TOS_AGREED=1"
"%ROOT%.venv312\Scripts\python.exe" -m ominvox.app %*
