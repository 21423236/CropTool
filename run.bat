@echo off
cd /d "%~dp0"
if exist "dist\CutImage.exe" (
    start "" "dist\CutImage.exe"
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
) else (
    echo Please run build.ps1 first.
    pause
)
