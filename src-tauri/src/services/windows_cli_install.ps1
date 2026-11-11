param(
    [Parameter(Mandatory=$true)][ValidateSet('claude','codex')][string]$Cli,
    [ValidateSet('install','update','reinstall')][string]$Action = 'install',
    [switch]$Quiet
)
$ErrorActionPreference = 'Stop'
$package = if ($Cli -eq 'claude') { '@anthropic-ai/claude-code' } else { '@openai/codex' }
$mutex = New-Object Threading.Mutex($false, 'Local\CCLauncherNpmInstall')
$locked = $false
$result = 1
$stage = $null
$logDir = Join-Path $env:LOCALAPPDATA 'CCLauncher\logs'
$null = New-Item -ItemType Directory -Force -Path $logDir
$logFile = Join-Path $logDir ("install-$Cli-" + [Guid]::NewGuid().ToString('N') + '.log')

function Invoke-Npm([string[]]$Arguments) {
    & $script:npm @Arguments
    if ($LASTEXITCODE -ne 0) { throw "npm failed (exit $LASTEXITCODE). See $logFile" }
}

function Assert-NotRunning([string]$PackageDir) {
    if (-not (Test-Path -LiteralPath $PackageDir)) { return }
    foreach ($exe in Get-ChildItem -LiteralPath $PackageDir -Recurse -File -Filter '*.exe') {
        try {
            $stream = [IO.File]::Open($exe.FullName, 'Open', 'Write', 'ReadWrite')
            $stream.Dispose()
        } catch { throw "Cannot replace $($exe.FullName). Close this CLI before updating. $($_.Exception.Message)" }
    }
}

try {
    Start-Transcript -Path $logFile -Force | Out-Null
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Another CLI installation is in progress. Wait for it to finish.' }
    $script:npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $prefix = (& $script:npm prefix -g | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not [IO.Path]::IsPathRooted($prefix)) { throw 'Cannot resolve npm global prefix' }
    $root = (& $script:npm root -g | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not [IO.Path]::IsPathRooted($root)) { throw 'Cannot resolve npm global root' }
    $packageDir = Join-Path $root $package
    $probe = Join-Path $PSScriptRoot 'windows_cli_probe.cjs'
    Assert-NotRunning $packageDir
    Write-Host "$Action $package (npm prefix: $prefix)"

    # Fetch the large native archive BEFORE touching the working installation.
    # A required dependency in an empty staging directory makes download errors
    # fatal. The subsequent global install consumes the verified npm cache.
    $latestJson = (& $script:npm view "$package@latest" --json | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot fetch CLI release metadata' }
    $latest = $latestJson | ConvertFrom-Json
    $arch = (& node -p 'process.arch' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $arch -notin @('x64','arm64')) { throw "Unsupported Node architecture: $arch" }
    $nativePackage = "$package-win32-$arch"
    $nativeVersion = $latest.optionalDependencies.$nativePackage
    if ($nativeVersion) {
        Write-Host "Downloading and verifying $nativePackage before modifying the current installation..."
        $stage = Join-Path ([IO.Path]::GetTempPath()) ('cclauncher-native-' + [Guid]::NewGuid().ToString('N'))
        $null = New-Item -ItemType Directory -Path $stage
        Invoke-Npm -Arguments @('install', "--prefix=$stage", '--global=false', '--no-save', '--package-lock=false', '--ignore-scripts=true', "$nativePackage@$nativeVersion", '--fetch-retries=2', '--fetch-timeout=1800000', '--no-audit', '--no-fund')
    }

    # Optional platform packages can fail with npm exit 0. Include them explicitly
    # and verify the installed binary, not just npm's exit code.
    Assert-NotRunning $packageDir
    if ($Action -eq 'reinstall') { Invoke-Npm -Arguments @('uninstall', '-g', "--prefix=$prefix", $package) }
    Invoke-Npm -Arguments @('install', '-g', "--prefix=$prefix", "$package@$($latest.version)", '--include=optional', '--ignore-scripts=false', '--foreground-scripts', '--fetch-retries=2', '--fetch-timeout=1800000')
    & node $probe $packageDir $Cli
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'CLI verification failed. Fetching its exact platform package as a required dependency...'
        $manifest = Get-Content -LiteralPath (Join-Path $packageDir 'package.json') -Raw | ConvertFrom-Json
        $arch = (& node -p 'process.arch' | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $arch -notin @('x64','arm64')) { throw "Unsupported Node architecture: $arch" }
        $nativePackage = "$package-win32-$arch"
        $nativeVersion = $manifest.optionalDependencies.$nativePackage
        if (-not $nativeVersion) { throw "No native dependency declared for $nativePackage" }
        # Use an empty staging project: installing directly inside the wrapper
        # still inherits optionalDependencies and can silently swallow failures.
        if (-not $stage) {
            $stage = Join-Path ([IO.Path]::GetTempPath()) ('cclauncher-native-' + [Guid]::NewGuid().ToString('N'))
            $null = New-Item -ItemType Directory -Path $stage
            Invoke-Npm -Arguments @('install', "--prefix=$stage", '--global=false', '--no-save', '--package-lock=false', '--ignore-scripts=true', "$nativePackage@$nativeVersion", '--fetch-retries=2', '--fetch-timeout=1800000', '--no-audit', '--no-fund')
        }
        $source = Join-Path (Join-Path $stage 'node_modules') $nativePackage
        $destination = Join-Path (Join-Path $packageDir 'node_modules') $nativePackage
        $null = New-Item -ItemType Directory -Force -Path $destination
        Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $destination -Recurse -Force
        Invoke-Npm -Arguments @('rebuild', '-g', "--prefix=$prefix", $package, '--ignore-scripts=false', '--foreground-scripts')
        & node $probe $packageDir $Cli
        if ($LASTEXITCODE -ne 0) { throw 'Native component repair failed verification' }
    }
    $shim = Join-Path $prefix "$Cli.cmd"
    if (-not (Test-Path -LiteralPath $shim)) { throw "Command shim missing: $shim" }
    & $shim --version
    if ($LASTEXITCODE -ne 0) { throw 'Installed command shim failed to start' }
    # Do not silently declare success when PATH still selects another installation.
    $resolved = (Get-Command $Cli -ErrorAction Stop).Source
    if ([IO.Path]::GetDirectoryName($resolved).TrimEnd('\') -ine $prefix.TrimEnd('\')) {
        throw "PATH selects $resolved instead of $shim. Resolve the duplicate installation first."
    }
    Write-Host "[OK] $Cli $Action completed and startup verified." -ForegroundColor Green
    $result = 0
} catch {
    Write-Host "[FAILED] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $logFile"
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    if ($stage) {
        $stagePath = [IO.Path]::GetFullPath($stage)
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if ($stagePath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
            [IO.Path]::GetFileName($stagePath).StartsWith('cclauncher-native-')) {
            Remove-Item -LiteralPath $stagePath -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    try { Stop-Transcript | Out-Null } catch {}
}
if (-not $Quiet) { Read-Host 'Press Enter to close' | Out-Null }
exit $result
