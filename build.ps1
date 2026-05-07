# Tauri 构建脚本 - 自动修复图标
# 用法: .\build.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Tauri Build with Icon Fix" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 运行 Tauri 构建
Write-Host "`n[1/3] Building Tauri app..." -ForegroundColor Yellow
npm run tauri build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

# 2. 用 rcedit 修复图标
Write-Host "`n[2/3] Fixing icon with rcedit..." -ForegroundColor Yellow
$exePath = "src-tauri\target\release\cc-launcher-tauri.exe"
$icoPath = "src-tauri\icons\icon.ico"
$rceditPath = "rcedit.exe"

if (Test-Path $rceditPath) {
    & $rceditPath $exePath --set-icon $icoPath
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Icon fixed successfully!" -ForegroundColor Green
    } else {
        Write-Host "Failed to fix icon" -ForegroundColor Red
    }
} else {
    Write-Host "rcedit.exe not found, downloading..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe" -OutFile $rceditPath
    & $rceditPath $exePath --set-icon $icoPath
}

# 3. 完成
Write-Host "`n[3/3] Build complete!" -ForegroundColor Green
Write-Host "Output: $exePath" -ForegroundColor Cyan
