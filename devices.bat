@echo off
REM Lists loopback (capture) + output devices, writes to devices_output.txt
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "HF_HOME=%ROOT%.cache\huggingface"
set "TORCH_HOME=%ROOT%.cache\torch"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"
"%ROOT%.venv312\Scripts\python.exe" -m ominvox.app --list-devices > "%ROOT%devices_output.txt" 2>&1
echo done
