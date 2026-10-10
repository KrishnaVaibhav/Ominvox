@echo off
REM Imports every ominvox module to catch syntax/import errors, writes result to file.
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "HF_HOME=%ROOT%.cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%ROOT%.cache\huggingface\hub"
set "TORCH_HOME=%ROOT%.cache\torch"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
"%ROOT%.venv312\Scripts\python.exe" -c "import ominvox.app, ominvox.orchestrator, ominvox.ui, ominvox.capture, ominvox.player, ominvox.voices, ominvox.diarize, ominvox.mt, ominvox.stt, ominvox.vad, ominvox.speaker_id, ominvox.config; print('IMPORT_OK all modules')" > "%ROOT%verify_output.txt" 2>&1
echo done
