@echo off
REM ===== Ominvox setup on Python 3.12 via conda. Env + caches stay in this folder. =====
setlocal enabledelayedexpansion
set "ROOT=%~dp0..\"
cd /d "%ROOT%"

REM --- all caches inside the project (nothing on C:) ---
set "HF_HOME=%ROOT%.cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%ROOT%.cache\huggingface\hub"
set "TORCH_HOME=%ROOT%.cache\torch"
set "PIP_CACHE_DIR=%ROOT%.cache\pip"
set "TTS_HOME=%ROOT%.cache\tts"
set "XDG_CACHE_HOME=%ROOT%.cache"
set "CONDA_PKGS_DIRS=%ROOT%.cache\conda-pkgs"
mkdir "%ROOT%.cache" 2>nul
mkdir "%ROOT%.cache\speakers" 2>nul

REM --- locate a conda installation ---
set "CONDA_ACT="
for %%P in (
  "%USERPROFILE%\anaconda3\Scripts\activate.bat"
  "%USERPROFILE%\miniconda3\Scripts\activate.bat"
  "%USERPROFILE%\Anaconda3\Scripts\activate.bat"
  "%ProgramData%\anaconda3\Scripts\activate.bat"
  "%ProgramData%\Anaconda3\Scripts\activate.bat"
  "C:\ProgramData\Anaconda3\Scripts\activate.bat"
) do if exist "%%~P" set "CONDA_ACT=%%~P"

if "!CONDA_ACT!"=="" (
  echo ERROR: could not find conda. Open "Anaconda Prompt" and run "where conda",
  echo then set CONDA_ACT in this script to that Scripts\activate.bat path.
  pause & exit /b 1
)
echo Using conda: !CONDA_ACT!
call "!CONDA_ACT!"

REM --- create the project-local 3.12 env ---
set "ENV=%ROOT%.venv312"
echo Creating Python 3.12 env at %ENV% ...
call conda create --yes --prefix "%ENV%" python=3.12
call conda activate "%ENV%"

python -m pip install --upgrade pip

echo.
echo === Core requirements (no torch yet) ===
pip install -r "%ROOT%requirements.txt"

echo.
echo === Coqui TTS fork (pulls a CPU torch; replaced below) ===
pip install coqui-tts

echo.
echo === GPU PyTorch LAST so it wins (CUDA 12.4). Edit cu124 if your driver differs. ===
pip uninstall -y torch torchaudio
pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu124

echo.
echo === Dependency self-test -> check_output.txt ===
python -m ominvox.app --check > "%ROOT%check_output.txt" 2>&1
type "%ROOT%check_output.txt"
echo.
echo ===== SETUP COMPLETE =====
endlocal
