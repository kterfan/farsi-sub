@echo off
rem Launch the FarsiSub window. Double-click this file.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
start "" ".venv\Scripts\pythonw.exe" -m farsisub.gui
