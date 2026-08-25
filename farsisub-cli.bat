@echo off
rem Command line: farsisub-cli video.mp4 --profile reels
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
".venv\Scripts\python.exe" -m farsisub.cli %*
