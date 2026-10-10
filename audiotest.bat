@echo off
REM Captures system audio for 15s and shows the live level. PLAY A MOVIE while it runs.
REM Result is written to audiotest_output.txt (and shown in this window).
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "HF_HOME=%ROOT%.cache\huggingface"
set "TORCH_HOME=%ROOT%.cache\torch"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"
echo ==== PLAY AUDIO NOW (movie/music). Capturing 15 seconds... ====
"%ROOT%.venv312\Scripts\python.exe" -m ominvox.app --audio-test --audio-seconds 15 > "%ROOT%audiotest_output.txt" 2>&1
type "%ROOT%audiotest_output.txt"
echo.
echo ==== done — results saved to audiotest_output.txt ====
pause
