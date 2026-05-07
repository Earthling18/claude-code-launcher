@echo off
chcp 65001 >nul
cd /d "%~dp0src-tauri\target\release"
if not exist "cc-launcher-tauri.exe" (
    echo Error: release exe not found!
    echo Please run: cargo build --release
    pause
    exit /b 1
)
start "" "cc-launcher-tauri.exe"
exit