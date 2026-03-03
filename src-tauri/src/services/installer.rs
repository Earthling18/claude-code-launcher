use std::process::Command;

pub struct Installer;

impl Installer {
    pub fn install_nodejs() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_nodejs_install_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_nodejs_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_nodejs() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_nodejs_update_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_nodejs_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn install_claude() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_claude_install_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_claude_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_claude() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_claude_update_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_claude_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn install_codex() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_codex_install_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_codex_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_codex() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_codex_update_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_codex_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn install_gitbash() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_gitbash_install_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_git_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_gitbash() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_gitbash_update_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_git_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    // ==================== Windows Scripts ====================

    #[cfg(windows)]
    fn generate_nodejs_install_script_windows() -> String {
        r#"
Write-Host '正在安装 Node.js LTS...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if (-not $wingetCmd) {
    Write-Host '✗ winget 不可用' -ForegroundColor Red
    Write-Host '正在打开 Node.js 下载页面...' -ForegroundColor Yellow
    Start-Process 'https://nodejs.org/en/download/'
    Write-Host ''
    Write-Host '按任意键关闭此窗口...'
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    exit
}

Write-Host '提示:安装过程中会显示进度条,请耐心等待' -ForegroundColor Yellow
Write-Host ''
winget install OpenJS.NodeJS.LTS
$wingetExitCode = $LASTEXITCODE
Write-Host ''
if ($wingetExitCode -eq 0) {
    Write-Host '✓ 安装成功完成!' -ForegroundColor Green
} elseif ($wingetExitCode -eq -1978335189 -or $wingetExitCode -eq -1978335212) {
    Write-Host 'ℹ Node.js 已安装' -ForegroundColor Cyan
} else {
    Write-Host "✗ 安装失败! (错误代码: $wingetExitCode)" -ForegroundColor Red
    winget install OpenJS.NodeJS.LTS --force
}
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    #[cfg(windows)]
    fn generate_nodejs_update_script_windows() -> String {
        r#"
Write-Host '正在更新 Node.js...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if (-not $wingetCmd) {
    Write-Host '✗ winget 不可用' -ForegroundColor Red
    Start-Process 'https://nodejs.org/en/download/'
    Write-Host '按任意键关闭此窗口...'
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    exit
}

winget upgrade OpenJS.NodeJS.LTS
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    #[cfg(windows)]
    fn generate_claude_install_script_windows() -> String {
        r#"@echo off
echo Installing Claude Code...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @anthropic-ai/claude-code
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @anthropic-ai/claude-code
    ) else (
        echo npm not found. Please make sure Node.js is installed.
        pause
        exit /b 1
    )
)
if %errorlevel%==0 (
    echo.
    echo [OK] Installation completed!
) else (
    echo.
    echo [FAILED] Installation failed!
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_claude_update_script_windows() -> String {
        r#"@echo off
echo Updating Claude Code...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @anthropic-ai/claude-code@latest
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @anthropic-ai/claude-code@latest
    ) else (
        echo npm not found.
        pause
        exit /b 1
    )
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_codex_install_script_windows() -> String {
        r#"@echo off
echo Installing Codex CLI...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @openai/codex
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @openai/codex
    ) else (
        echo npm not found. Please make sure Node.js is installed.
        pause
        exit /b 1
    )
)
if %errorlevel%==0 (
    echo.
    echo [OK] Installation completed!
) else (
    echo.
    echo [FAILED] Installation failed!
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_codex_update_script_windows() -> String {
        r#"@echo off
echo Updating Codex CLI...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @openai/codex@latest
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @openai/codex@latest
    ) else (
        echo npm not found.
        pause
        exit /b 1
    )
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_gitbash_install_script_windows() -> String {
        r#"
Write-Host '正在安装 Git...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if (-not $wingetCmd) {
    Write-Host '✗ winget 不可用' -ForegroundColor Red
    Start-Process 'https://git-scm.com/download/windows'
    Write-Host '按任意键关闭此窗口...'
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    exit
}

winget install --id Git.Git -e --source winget
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    #[cfg(windows)]
    fn generate_gitbash_update_script_windows() -> String {
        r#"
Write-Host '正在更新 Git...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if (-not $wingetCmd) {
    Write-Host '✗ winget 不可用' -ForegroundColor Red
    Start-Process 'https://git-scm.com/download/windows'
    Write-Host '按任意键关闭此窗口...'
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    exit
}

winget upgrade --id Git.Git -e --source winget
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    // ==================== macOS Scripts ====================

    #[cfg(target_os = "macos")]
    fn generate_nodejs_install_script_macos() -> String {
        r#"
echo "正在安装 Node.js..."
echo ""

# 1. Check if node is already installed
if command -v node &> /dev/null; then
    echo "✓ Node.js 已安装:"
    node --version
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 2. Try Homebrew if available
if command -v brew &> /dev/null; then
    echo "使用 Homebrew 安装 Node.js..."
    brew install node
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ 安装成功完成!"
        node --version
    else
        echo ""
        echo "✗ Homebrew 安装失败!"
    fi
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 3. No Homebrew — install Homebrew first, then node
echo "未检测到 Homebrew，将先安装 Homebrew..."
echo ""
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add brew to PATH for current session (Apple Silicon vs Intel)
if [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -f /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

if command -v brew &> /dev/null; then
    echo ""
    echo "Homebrew 安装成功，正在安装 Node.js..."
    brew install node
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ Node.js 安装成功!"
        node --version
    else
        echo "✗ Node.js 安装失败!"
    fi
else
    echo ""
    echo "✗ Homebrew 安装失败，正在打开 Node.js 下载页面..."
    open "https://nodejs.org/en/download/"
fi

echo ""
read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_nodejs_update_script_macos() -> String {
        r#"
echo "正在更新 Node.js..."
echo ""

# Try Homebrew if available
if command -v brew &> /dev/null; then
    export HOMEBREW_NO_AUTO_UPDATE=1
    export HOMEBREW_NO_ENV_HINTS=1
    # Check if node was installed via brew
    if brew list node &> /dev/null; then
        brew upgrade node 2>/dev/null || echo "Node.js 已是最新版本"
    else
        # Node exists but not via brew — reinstall through brew to manage future updates
        echo "当前 Node.js 非 Homebrew 安装，正在通过 Homebrew 重新安装以便管理更新..."
        brew install node
    fi
    echo ""
    echo "✓ 更新完成!"
    node --version
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# No Homebrew — install Homebrew first, then upgrade
echo "未检测到 Homebrew，正在安装 Homebrew..."
echo ""
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add brew to PATH for current session (Apple Silicon vs Intel)
if [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -f /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

if command -v brew &> /dev/null; then
    echo ""
    echo "✓ Homebrew 安装成功，正在更新 Node.js..."
    brew upgrade node
    echo ""
    echo "✓ 更新完成!"
    node --version
else
    echo ""
    echo "✗ Homebrew 安装失败，正在打开 Node.js 下载页面..."
    open "https://nodejs.org/en/download/"
fi

echo ""
read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_claude_install_script_macos() -> String {
        r#"
echo "Installing Claude Code..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found. Please install Node.js first."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @anthropic-ai/claude-code

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Installation completed!"
else
    echo ""
    echo "✗ Installation failed!"
fi

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_claude_update_script_macos() -> String {
        r#"
echo "Updating Claude Code..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @anthropic-ai/claude-code@latest

echo ""
echo "✓ Update completed!"

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_codex_install_script_macos() -> String {
        r#"
echo "Installing Codex CLI..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found. Please install Node.js first."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @openai/codex

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Installation completed!"
else
    echo ""
    echo "✗ Installation failed!"
fi

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_codex_update_script_macos() -> String {
        r#"
echo "Updating Codex CLI..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @openai/codex@latest

echo ""
echo "✓ Update completed!"

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_git_install_script_macos() -> String {
        r#"
echo "正在安装 Git..."
echo ""

# 1. Check if git is already installed
if command -v git &> /dev/null; then
    echo "✓ Git 已安装:"
    git --version
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 2. Try xcode-select (system native way)
echo "正在通过 Xcode Command Line Tools 安装 Git..."
xcode-select --install 2>/dev/null
if [ $? -eq 0 ]; then
    echo ""
    echo "已弹出 Xcode Command Line Tools 安装窗口，请完成安装后重新检测。"
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 3. Try Homebrew if available
echo "Xcode Command Line Tools 安装失败，尝试 Homebrew..."
if command -v brew &> /dev/null; then
    export HOMEBREW_NO_AUTO_UPDATE=1
    export HOMEBREW_NO_ENV_HINTS=1
    brew install git
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ 安装成功!"
        git --version
    else
        echo "✗ 安装失败!"
    fi
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 4. No Homebrew — install Homebrew first, then git
echo "未检测到 Homebrew，将先安装 Homebrew..."
echo ""
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add brew to PATH for current session (Apple Silicon vs Intel)
if [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -f /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

if command -v brew &> /dev/null; then
    echo ""
    echo "Homebrew 安装成功，正在安装 Git..."
    brew install git
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ Git 安装成功!"
        git --version
    else
        echo "✗ Git 安装失败!"
    fi
else
    echo ""
    echo "✗ Homebrew 安装失败，正在打开 Git 下载页面..."
    open "https://git-scm.com/download/mac"
fi

echo ""
read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_git_update_script_macos() -> String {
        r#"
echo "正在更新 Git..."
echo ""

# Check if git is installed via brew
if command -v brew &> /dev/null; then
    export HOMEBREW_NO_AUTO_UPDATE=1
    export HOMEBREW_NO_ENV_HINTS=1
    if brew list git &> /dev/null; then
        brew upgrade git 2>/dev/null || echo "Git 已是最新版本"
        echo ""
        echo "✓ 更新完成!"
        git --version
        read -p "按回车键关闭此窗口..."
        exit 0
    fi
fi

# Git installed via Xcode Command Line Tools — try softwareupdate
echo "当前 Git 由 Xcode Command Line Tools 提供，正在尝试系统更新..."
softwareupdate -l 2>&1 | grep -i "command line"
if [ $? -eq 0 ]; then
    echo "发现可用更新，正在安装..."
    softwareupdate -i "$(softwareupdate -l 2>&1 | grep -i 'command line' | grep -oE '\*.*' | sed 's/^\* Label: //')" --agree-to-license 2>/dev/null
    echo ""
    echo "✓ 更新完成!"
    git --version
else
    echo "当前已是最新版本"
    echo ""
    git --version
fi

read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    // ==================== Execution Functions ====================

    #[cfg(windows)]
    fn execute_powershell_script(script: &str) -> Result<(), String> {
        use std::os::windows::process::CommandExt;
        const CREATE_NEW_CONSOLE: u32 = 0x00000010;

        Command::new("powershell")
            .arg("-Command")
            .arg(script)
            .creation_flags(CREATE_NEW_CONSOLE)
            .spawn()
            .map_err(|e| format!("无法启动PowerShell: {}", e))?;

        Ok(())
    }

    #[cfg(windows)]
    fn execute_cmd_script(script: &str) -> Result<(), String> {
        use std::os::windows::process::CommandExt;
        use std::io::Write;
        const CREATE_NEW_CONSOLE: u32 = 0x00000010;

        let temp_dir = std::env::temp_dir();
        let batch_file = temp_dir.join("claude_install.bat");

        let mut file = std::fs::File::create(&batch_file)
            .map_err(|e| format!("无法创建临时批处理文件: {}", e))?;
        file.write_all(script.as_bytes())
            .map_err(|e| format!("无法写入批处理文件: {}", e))?;

        Command::new("cmd")
            .args(&["/k", batch_file.to_str().unwrap()])
            .creation_flags(CREATE_NEW_CONSOLE)
            .spawn()
            .map_err(|e| format!("无法启动CMD: {}", e))?;

        Ok(())
    }

    #[cfg(target_os = "macos")]
    fn execute_terminal_script(script: &str) -> Result<(), String> {
        use std::io::Write;

        // Create temp script file
        let temp_dir = std::env::temp_dir();
        let script_file = temp_dir.join("claude_install.sh");

        let mut file = std::fs::File::create(&script_file)
            .map_err(|e| format!("无法创建临时脚本文件: {}", e))?;
        file.write_all(script.as_bytes())
            .map_err(|e| format!("无法写入脚本文件: {}", e))?;

        // Make executable
        Command::new("chmod")
            .args(&["+x", script_file.to_str().unwrap()])
            .output()
            .map_err(|e| format!("无法设置执行权限: {}", e))?;

        // Open in Terminal.app
        let apple_script = format!(
            r#"tell application "Terminal"
                activate
                do script "{}"
            end tell"#,
            script_file.display()
        );

        Command::new("osascript")
            .args(&["-e", &apple_script])
            .spawn()
            .map_err(|e| format!("无法启动Terminal: {}", e))?;

        Ok(())
    }
}
