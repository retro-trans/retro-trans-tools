@echo off
cd /d "%~dp0"
if exist "dist\Retro-Trans.exe" (
    start "" "dist\Retro-Trans.exe"
    exit /b
)
py -3 launch.py
if errorlevel 1 pause
