# Fetch Windows Terminal Portable into src-tauri/resources/wt/
#
# Used by CI (.github/workflows/build.yml) and local dev. The bundled WT is the
# fallback terminal when the user's system has no wt.exe, so Claude Code never
# lands in legacy conhost (lag / garbled screen / crash on resize).
#
# Compatible with Windows PowerShell 5.1 and PowerShell 7.

param(
    [string]$Version = "1.24.11321.0",
    [string]$Sha256 = "7CAEF554147E5498ED1BECDCA73CDEDB79FBC81F89032E46AE9B095C53433812",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $repoRoot "src-tauri\resources\wt"
$zipName = "Microsoft.WindowsTerminal_${Version}_x64.zip"
$url = "https://github.com/microsoft/terminal/releases/download/v$Version/$zipName"

if ((Test-Path (Join-Path $targetDir "WindowsTerminal.exe")) -and -not $Force) {
    Write-Host "Windows Terminal already present in $targetDir (use -Force to re-fetch)"
    exit 0
}

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "wt-fetch-$Version"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$zipPath = Join-Path $tempDir $zipName

if (-not (Test-Path $zipPath)) {
    Write-Host "Downloading $url ..."
    # Invoke-WebRequest is painfully slow in PS 5.1 with the progress bar on.
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
}

$actualHash = (Get-FileHash $zipPath -Algorithm SHA256).Hash
if ($actualHash -ne $Sha256.ToUpper()) {
    Remove-Item $zipPath -Force
    throw "SHA256 mismatch for ${zipName}: expected $Sha256, got $actualHash"
}
Write-Host "SHA256 OK"

$extractDir = Join-Path $tempDir "extracted"
if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

# The zip wraps everything in a single "terminal-<version>" folder; flatten it.
$srcDir = $extractDir
$children = @(Get-ChildItem $extractDir)
if ($children.Count -eq 1 -and $children[0].PSIsContainer) {
    $srcDir = $children[0].FullName
}
if (-not (Test-Path (Join-Path $srcDir "WindowsTerminal.exe"))) {
    throw "WindowsTerminal.exe not found in extracted archive ($srcDir)"
}

# Refresh target dir but keep the placeholder README tracked by git.
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
Get-ChildItem $targetDir -Force | Where-Object { $_.Name -ne "README.md" } | Remove-Item -Recurse -Force
Get-ChildItem $srcDir -Force | Move-Item -Destination $targetDir -Force

# Portable-mode marker: WT keeps settings beside the exe instead of the user's
# profile. The launcher also creates this at runtime as a safety net.
New-Item -ItemType File -Force -Path (Join-Path $targetDir ".portable") | Out-Null

Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Windows Terminal $Version ready in $targetDir"
