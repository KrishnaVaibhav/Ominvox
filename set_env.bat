@echo off
REM Pin all caches into the project folder. Run after activating the venv, before python.
set "ROOT=%~dp0"
set "HF_HOME=%ROOT%.cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%ROOT%.cache\huggingface\hub"
set "TORCH_HOME=%ROOT%.cache\torch"
set "PIP_CACHE_DIR=%ROOT%.cache\pip"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"
set "COQUI_TOS_AGREED=1"
echo Ominvox env pinned to %ROOT%.cache
