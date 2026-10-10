@echo off
REM Runs the Ominvox dependency self-test and writes results to a file.
call "%~dp0run.bat" --check > "%~dp0check_output.txt" 2>&1
echo done
