$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create virtual environment' }
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Failed to install dependencies' }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Failed to create application icon' }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name CutImage --icon assets\app.ico --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets main.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
Write-Host "Built: $PSScriptRoot\dist\CutImage.exe"
