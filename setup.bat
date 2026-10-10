@echo off
REM ===== Ominvox setup - everything stays under D:\GitHub\Ominvox, nothing on C: =====
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

REM --- all model/download caches live inside the project ---
set "HF_HOME=%ROOT%.cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%ROOT%.cache\huggingface\hub"
set "TORCH_HOME=%ROOT%.cache\torch"
set "PIP_CACHE_DIR=%ROOT%.cache\pip"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"

mkdir "%ROOT%.cache" 2>nul
mkdir "%ROOT%.cache\speakers" 2>nul

echo Creating project-local venv at %ROOT%.venv ...
python -m venv "%ROOT%.venv"
call "%ROOT%.venv\Scripts\activate.bat"

python -m pip install --upgrade pip

echo.
echo === Installing GPU PyTorch (CUDA 12.1 build). Edit the index-url for your CUDA. ===
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

echo.
echo === Installing remaining requirements ===
pip install -r "%ROOT%requirements.txt"

echo.
echo Done. Activate later with:  call .venv\Scripts\activate.bat  ^&^&  set_env.bat
echo Then run:  python -m ominvox.app
endlocal
