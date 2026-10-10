@echo off
REM Listens to your speakers for 15 s and shows the sound level. PLAY SOMETHING while it runs.
echo ==== Play a movie or music now. Listening for 15 seconds... ====
call "%~dp0..\run.bat" --audio-test --audio-seconds 15
pause
