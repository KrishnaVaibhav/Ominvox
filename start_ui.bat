@echo off
REM One-click launch: starts the Ominvox web UI and opens it in your browser.
cd /d "%~dp0"
call "%~dp0run.bat" --ui
pause
