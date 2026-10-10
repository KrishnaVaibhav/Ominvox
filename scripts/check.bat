@echo off
REM Self-test: are all packages installed and is the GPU usable?
call "%~dp0..\run.bat" --check
pause
