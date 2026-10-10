@echo off
REM Lists every audio input/output with the numbers config.yaml uses.
call "%~dp0..\run.bat" --list-devices
pause
