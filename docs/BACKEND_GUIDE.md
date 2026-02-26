# 后端开发指南

> **技术栈**: Rust + Tauri 2 + Tokio + Windows/macOS API
> **最后更新**: 2026-02-26

---

## 📋 目录

- [1. 技术栈概览](#1-技术栈概览)
- [2. 项目结构](#2-项目结构)
- [3. 核心服务模块](#3-核心服务模块)
- [4. Commands 层](#4-commands-层)
- [5. 系统集成](#5-系统集成)
- [6. 错误处理](#6-错误处理)
- [7. 开发实践](#7-开发实践)

---

## 1. 技术栈概览

### 1.1 核心依赖

```toml
[dependencies]
tauri = { version = "2", features = [] }     # Tauri 框架
tauri-plugin-opener = "2"                    # 文件/URL 打开插件
tauri-plugin-dialog = "2"                    # 对话框插件
tauri-plugin-clipboard-manager = "2"         # 剪贴板插件 (macOS 必需)
serde = { version = "1", features = ["derive"] }  # 序列化框架
serde_json = "1"                            # JSON 序列化
tokio = { version = "1", features = ["full"] }    # 异步运行时
regex = "1"                                 # 正则表达式
base64 = "0.22"                             # Base64 编解码
reqwest = { version = "0.12", features = ["json"] }  # HTTP 客户端
dirs = "5.0"                                # 跨平台目录路径
```

### 1.2 Windows 特定依赖

```toml
[target.'cfg(windows)'.dependencies]
winreg = "0.52"                             # Windows 注册表访问

windows = { version = "0.58", features = [
    "Win32_Foundation",                      # 基础 Windows API
    "Win32_UI_WindowsAndMessaging",         # UI 和消息 API
    "Win32_System_Threading"                 # 进程和线程 API
] }
```

### 1.3 构建配置

```toml
[profile.release]
panic = "abort"          # panic 时直接终止，减小二进制大小
codegen-units = 1        # 单个代码生成单元，更好的优化
lto = true               # 链接时优化
opt-level = "s"          # 优化二进制文件大小
strip = true             # 移除调试符号
```

---

## 2. 项目结构

```
src-tauri/
├── src/
│   ├── main.rs                  # 程序入口 (main 函数)
│   ├── lib.rs                   # Tauri 应用构建 (27 个 Commands)
│   ├── commands/                # Commands 层
│   │   └── mod.rs              # 所有 Tauri Commands 定义
│   └── services/                # 服务层 (业务逻辑)
│       ├── mod.rs              # 模块导出
│       ├── dependency_checker.rs   # 依赖检测服务 (Node.js/Claude/Git Bash)
│       ├── installer.rs            # 安装/更新服务 (跨平台)
│       ├── launcher.rs             # 启动器服务 (PowerShell/CMD/Bash)
│       ├── settings_manager.rs     # Claude 设置管理
│       ├── config_storage.rs       # 应用配置存储 (含 skip_permissions)
│       └── environment.rs          # 环境变量管理
│
├── Cargo.toml                   # Rust 依赖配置
├── tauri.conf.json              # Tauri 应用配置 (跨平台打包)
├── build.rs                     # 构建脚本
├── capabilities/
│   └── default.json             # 权限配置
└── icons/                       # 应用图标资源 (含 .icns)
```

### 2.1 模块职责

| 模块 | 职责 |
|------|------|
| `main.rs` | 程序入口，启动 Tauri 应用 |
| `lib.rs` | Tauri 应用配置和构建 |
| `commands/` | Tauri Commands 定义，前后端通信接口 |
| `services/` | 核心业务逻辑，系统调用封装 |

---

## 3. 核心服务模块

### 3.1 dependency_checker.rs - 依赖检测服务

#### 3.1.1 数据结构

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DependencyStatus {
    pub installed: bool,           // 是否已安装
    pub version: Option<String>,   // 当前版本号
    pub meets_requirement: bool,   // 是否满足最低版本要求
    pub latest_version: Option<String>,  // 最新可用版本
    pub update_available: bool,    // 是否有更新
    pub error: Option<String>,     // 错误信息
}
```

#### 3.1.2 macOS PATH 扩展

macOS GUI 应用通过 Finder/Dock 启动时不会继承 shell 的 PATH 环境变量（`.zshrc`/`.bash_profile` 不会被加载）。因此需要手动扩展 PATH 来查找 `node` 和 `claude` 命令。

```rust
#[cfg(target_os = "macos")]
fn get_macos_extended_path() -> String {
    let home = dirs::home_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| "".to_string());

    let mut extra_paths: Vec<String> = vec![
        "/usr/local/bin".to_string(),           // Homebrew (Intel Mac)
        "/opt/homebrew/bin".to_string(),        // Homebrew (Apple Silicon)
        "/opt/homebrew/sbin".to_string(),
    ];

    if !home.is_empty() {
        extra_paths.push(format!("{}/.npm-global/bin", home));  // npm global
        extra_paths.push(format!("{}/Library/pnpm", home));     // pnpm
        extra_paths.push(format!("{}/.local/bin", home));
        extra_paths.push(format!("{}/.volta/bin", home));       // Volta

        // nvm installations - 动态扫描
        let nvm_base = format!("{}/.nvm/versions/node", home);
        if let Ok(entries) = std::fs::read_dir(&nvm_base) {
            for entry in entries.flatten() {
                let bin_path = entry.path().join("bin");
                if bin_path.exists() {
                    extra_paths.push(bin_path.to_string_lossy().to_string());
                }
            }
        }

        // fnm installations - 动态扫描
        let fnm_base = format!("{}/Library/Application Support/fnm/node-versions", home);
        if let Ok(entries) = std::fs::read_dir(&fnm_base) {
            for entry in entries.flatten() {
                let bin_path = entry.path().join("installation/bin");
                if bin_path.exists() {
                    extra_paths.push(bin_path.to_string_lossy().to_string());
                }
            }
        }
    }

    // 合并到现有 PATH
    let current_path = env::var("PATH").unwrap_or_default();
    let mut all_paths: Vec<&str> = extra_paths.iter().map(|s| s.as_str()).collect();
    all_paths.extend(current_path.split(':'));

    all_paths.join(":")
}
```

#### 3.1.3 Node.js 检测

**主要函数**:

```rust
pub fn check_nodejs() -> DependencyStatus
```

**实现逻辑** (跨平台):

```rust
pub fn check_nodejs() -> DependencyStatus {
    #[cfg(target_os = "macos")]
    {
        // macOS: 使用扩展 PATH
        let extended_path = get_macos_extended_path();
        let output = Command::new("sh")
            .args(&["-c", &format!("PATH='{}' node --version", extended_path)])
            .output();
        // ... 处理结果
    }

    #[cfg(not(target_os = "macos"))]
    {
        // Windows/Linux: 直接执行
        Self::check_dependency("node", &["--version"], r"v(\d+\.\d+\.\d+)", Some("18.0.0"))
    }
}
```

**检测最新版本**:

```rust
pub fn check_nodejs_with_update() -> DependencyStatus {
    let mut status = check_nodejs();

    if status.installed {
        // 通过 winget show 获取最新版本
        if let Ok(output) = Command::new("winget")
            .args(["show", "OpenJS.NodeJS.LTS"])
            .output()
        {
            if output.status.success() {
                let output_str = String::from_utf8_lossy(&output.stdout);

                // 解析 Version: 22.0.0
                let re = Regex::new(r"Version:\s*(\d+\.\d+\.\d+)").unwrap();
                if let Some(caps) = re.captures(&output_str) {
                    let latest = caps.get(1).unwrap().as_str().to_string();
                    status.latest_version = Some(latest.clone());

                    // 比较版本判断是否有更新
                    if let Some(ref current) = status.version {
                        status.update_available =
                            compare_versions(&latest, current) > 0;
                    }
                }
            }
        }
    }

    status
}
```

#### 3.1.4 Claude Code 检测

**主要函数**:

```rust
pub fn check_claude() -> DependencyStatus
```

**跨平台检测**:

```rust
pub fn check_claude() -> DependencyStatus {
    #[cfg(windows)]
    Self::refresh_system_path();

    // Windows: 使用 cmd
    #[cfg(windows)]
    let output = Command::new("cmd")
        .args(&["/c", "claude", "--version"])
        .output();

    // macOS: 使用扩展 PATH
    #[cfg(target_os = "macos")]
    let output = {
        let extended_path = get_macos_extended_path();
        Command::new("sh")
            .args(&["-c", &format!("PATH='{}' claude --version", extended_path)])
            .output()
    };

    // Linux: 直接执行
    #[cfg(all(not(windows), not(target_os = "macos")))]
    let output = Command::new("claude")
        .arg("--version")
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let stdout = String::from_utf8_lossy(&out.stdout);

            // 多种版本号格式匹配
            let patterns = vec![
                r"(\d+\.\d+\.\d+)\s*\(Claude Code\)",
                r"v(\d+\.\d+\.\d+)",
                r"^(\d+\.\d+\.\d+)",
                r"(\d+\.\d+\.\d+)",
            ];

            for pattern in patterns {
                if let Ok(re) = Regex::new(pattern) {
                    if let Some(caps) = re.captures(&stdout) {
                        let version = caps.get(1).map(|m| m.as_str().to_string());
                        return DependencyStatus {
                            installed: true,
                            version,
                            meets_requirement: true,
                            ..Default::default()
                        };
                    }
                }
            }
            // 已安装但无法解析版本
            DependencyStatus { installed: true, ..Default::default() }
        }
        _ => DependencyStatus {
            installed: false,
            error: Some("Claude Code not found".to_string()),
            ..Default::default()
        },
    }
}
```

#### 3.1.5 Git Bash 检测 (Windows)

**主要函数**:

```rust
pub fn check_gitbash() -> DependencyStatus
```

**检测逻辑**:

```rust
#[cfg(windows)]
pub fn check_gitbash() -> DependencyStatus {
    // 方法 1: git --version
    if let Ok(output) = Command::new("git").args(["--version"]).output() {
        if output.status.success() {
            let version_str = String::from_utf8_lossy(&output.stdout);

            // 提取版本号: git version 2.43.0.windows.1 -> 2.43.0
            let re = Regex::new(r"git version (\d+\.\d+\.\d+)").unwrap();
            if let Some(caps) = re.captures(&version_str) {
                let version = caps.get(1).unwrap().as_str().to_string();

                return DependencyStatus {
                    installed: true,
                    version: Some(version),
                    meets_requirement: true,
                    latest_version: None,
                    update_available: false,
                    error: None,
                };
            }
        }
    }

    // 方法 2: 检查 Git Bash 路径
    let git_bash_path = "C:\\Program Files\\Git\\bin\\bash.exe";
    if std::path::Path::new(git_bash_path).exists() {
        return DependencyStatus {
            installed: true,
            version: Some("unknown".to_string()),
            meets_requirement: true,
            latest_version: None,
            update_available: false,
            error: None,
        };
    }

    DependencyStatus {
        installed: false,
        version: None,
        meets_requirement: false,
        latest_version: None,
        update_available: false,
        error: Some("未安装或不在 PATH 中".to_string()),
    }
}

// macOS 版本
#[cfg(target_os = "macos")]
pub fn check_gitbash() -> DependencyStatus {
    // macOS 使用 git (通过 Homebrew 或 Xcode Command Line Tools)
    if let Ok(output) = Command::new("git").args(["--version"]).output() {
        if output.status.success() {
            let version_str = String::from_utf8_lossy(&output.stdout);
            let re = Regex::new(r"git version (\d+\.\d+\.\d+)").unwrap();
            if let Some(caps) = re.captures(&version_str) {
                return DependencyStatus {
                    installed: true,
                    version: Some(caps.get(1).unwrap().as_str().to_string()),
                    meets_requirement: true,
                    ..Default::default()
                };
            }
        }
    }

    DependencyStatus::default()
}
```

**从 npm registry 获取最新版本**:

```rust
pub async fn get_latest_npm_version(package: &str) -> Result<String, String> {
    let url = format!("https://registry.npmjs.org/{}/latest", package);

    let response = reqwest::get(&url)
        .await
        .map_err(|e| format!("请求失败: {}", e))?;

    let json: serde_json::Value = response
        .json()
        .await
        .map_err(|e| format!("解析 JSON 失败: {}", e))?;

    json["version"]
        .as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| "未找到版本信息".to_string())
}

pub async fn check_claude_with_update() -> DependencyStatus {
    let mut status = check_claude();

    if status.installed {
        // 从 npm registry 获取最新版本
        if let Ok(latest) = get_latest_npm_version("@anthropic-ai/claude-code").await {
            status.latest_version = Some(latest.clone());

            if let Some(ref current) = status.version {
                status.update_available = compare_versions(&latest, current) > 0;
            }
        }
    }

    status
}
```

#### 3.1.6 版本比较

```rust
fn compare_versions(v1: &str, v2: &str) -> i32 {
    let parts1: Vec<u32> = v1.split('.')
        .filter_map(|s| s.parse().ok())
        .collect();
    let parts2: Vec<u32> = v2.split('.')
        .filter_map(|s| s.parse().ok())
        .collect();

    for i in 0..parts1.len().max(parts2.len()) {
        let p1 = parts1.get(i).copied().unwrap_or(0);
        let p2 = parts2.get(i).copied().unwrap_or(0);

        match p1.cmp(&p2) {
            std::cmp::Ordering::Greater => return 1,
            std::cmp::Ordering::Less => return -1,
            std::cmp::Ordering::Equal => continue,
        }
    }

    0  // 版本相同
}
```

#### 3.1.7 刷新系统 PATH (Windows)

```rust
#[cfg(windows)]
pub fn refresh_system_path() -> Result<(), String> {
    use winreg::enums::*;
    use winreg::RegKey;

    // 1. 打开注册表键
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);

    // 2. 读取系统 PATH
    let sys_env = hklm
        .open_subkey("SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment")
        .map_err(|e| format!("无法打开系统环境变量: {}", e))?;
    let system_path: String = sys_env
        .get_value("Path")
        .unwrap_or_default();

    // 3. 读取用户 PATH
    let usr_env = hkcu
        .open_subkey("Environment")
        .map_err(|e| format!("无法打开用户环境变量: {}", e))?;
    let user_path: String = usr_env
        .get_value("Path")
        .unwrap_or_default();

    // 4. 合并 PATH
    let new_path = format!("{};{}", system_path, user_path);

    // 5. 设置到当前进程
    std::env::set_var("PATH", &new_path);

    // 6. 去重 PATH
    let paths: Vec<&str> = new_path.split(';').collect();
    let mut unique_paths = Vec::new();
    for path in paths {
        if !path.is_empty() && !unique_paths.contains(&path) {
            unique_paths.push(path);
        }
    }
    let final_path = unique_paths.join(";");
    std::env::set_var("PATH", &final_path);

    Ok(())
}
```

---

### 3.2 installer.rs - 安装/更新服务

#### 3.2.1 Node.js 安装

```rust
#[cfg(windows)]
pub fn install_nodejs() -> Result<(), String> {
    // 检查 winget 是否可用
    if !is_winget_available() {
        open_nodejs_download_page()?;
        return Err("winget 不可用，请手动安装".to_string());
    }

    // PowerShell 脚本
    let script = r#"
Write-Host "正在安装 Node.js LTS..." -ForegroundColor Green
winget install OpenJS.NodeJS.LTS

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Node.js 安装成功！" -ForegroundColor Green
    Write-Host "请关闭此窗口并重新启动应用。" -ForegroundColor Yellow
} else {
    Write-Host "`n✗ Node.js 安装失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
    Write-Host "请检查网络连接或手动安装。" -ForegroundColor Yellow
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
"#;

    // 在新控制台窗口执行
    execute_powershell_in_new_window(script)
}
```

#### 3.2.2 Node.js 更新

```rust
#[cfg(windows)]
pub fn update_nodejs() -> Result<(), String> {
    if !is_winget_available() {
        return Err("winget 不可用".to_string());
    }

    let script = r#"
Write-Host "正在更新 Node.js..." -ForegroundColor Green
winget upgrade OpenJS.NodeJS.LTS

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Node.js 更新成功！" -ForegroundColor Green
} else {
    Write-Host "`n✗ Node.js 更新失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
"#;

    execute_powershell_in_new_window(script)
}
```

#### 3.2.3 Claude Code 安装

```rust
pub fn install_claude() -> Result<(), String> {
    let script = r#"
Write-Host "正在安装 Claude Code..." -ForegroundColor Green
npm install -g @anthropic-ai/claude-code

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Claude Code 安装成功！" -ForegroundColor Green
} else {
    Write-Host "`n✗ Claude Code 安装失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
    Write-Host "请检查 Node.js 是否正确安装。" -ForegroundColor Yellow
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
"#;

    execute_powershell_in_new_window(script)
}
```

#### 3.2.4 Claude Code 更新

```rust
pub fn update_claude() -> Result<(), String> {
    let script = r#"
Write-Host "正在更新 Claude Code..." -ForegroundColor Green
npm install -g @anthropic-ai/claude-code@latest

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Claude Code 更新成功！" -ForegroundColor Green
} else {
    Write-Host "`n✗ Claude Code 更新失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
"#;

    execute_powershell_in_new_window(script)
}
```

#### 3.2.5 辅助函数

**检查 winget 是否可用**:

```rust
fn is_winget_available() -> bool {
    Command::new("winget")
        .args(["--version"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}
```

**在新窗口执行 PowerShell**:

```rust
#[cfg(windows)]
fn execute_powershell_in_new_window(script: &str) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    use windows::Win32::System::Threading::CREATE_NEW_CONSOLE;

    Command::new("powershell")
        .args([
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command", script,
        ])
        .creation_flags(CREATE_NEW_CONSOLE.0)
        .spawn()
        .map_err(|e| format!("启动 PowerShell 失败: {}", e))?;

    Ok(())
}
```

**打开 Node.js 下载页面**:

```rust
fn open_nodejs_download_page() -> Result<(), String> {
    use std::process::Command;

    Command::new("cmd")
        .args(["/C", "start", "https://nodejs.org/"])
        .spawn()
        .map_err(|e| format!("打开下载页面失败: {}", e))?;

    Ok(())
}
```

---

### 3.3 launcher.rs - 启动器服务

#### 3.3.1 启动 Claude Code (Windows)

```rust
use std::collections::HashMap;
use std::process::Command;

#[cfg(windows)]
pub fn launch_with_config(config: HashMap<String, String>) -> Result<(), String> {
    // 1. 检查 claude 命令是否存在
    if !is_claude_available() {
        return Err("Claude Code 未安装或不在 PATH 中".to_string());
    }

    // 2. 获取用户主目录
    let home_dir = dirs::home_dir()
        .ok_or("无法获取用户主目录".to_string())?;

    // 3. 构建 PowerShell 脚本
    let mut env_vars = Vec::new();
    for (key, value) in config {
        let escaped_value = value.replace("\"", "`\"");
        env_vars.push(format!("$env:{}=\"{}\"", key, escaped_value));
    }

    let env_script = env_vars.join("; ");
    let script = format!("& {{ {}; claude }}", env_script);

    // 4. 在新控制台窗口启动
    use std::os::windows::process::CommandExt;
    use windows::Win32::System::Threading::CREATE_NEW_CONSOLE;

    Command::new("powershell")
        .args(["-NoExit", "-NoProfile", "-Command", &script])
        .current_dir(home_dir)
        .creation_flags(CREATE_NEW_CONSOLE.0)
        .spawn()
        .map_err(|e| format!("启动失败: {}", e))?;

    Ok(())
}
```

#### 3.3.2 启动 Claude Code (macOS)

**重要**: macOS 上不预检查 `claude` 命令是否存在，因为:
1. Terminal.app 以登录 shell 启动，会加载 `.zshrc`/`.bash_profile`
2. 因此 Terminal 中的 PATH 是完整的（包含 npm global、homebrew、nvm 等）
3. 而 GUI 应用不继承这些 PATH，`which claude` 会失败即使 claude 已安装
4. 如果 claude 真的未安装，用户会在 Terminal 中直接看到错误

```rust
#[cfg(target_os = "macos")]
fn execute_macos(command: &str, working_dir: Option<String>) -> Result<(), String> {
    // 注意: 不检查 claude 是否存在，因为 Terminal 中 PATH 是正确的

    let target_dir = working_dir.unwrap_or_else(|| {
        dirs::home_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "~".to_string())
    });

    // 使用 osascript 打开 Terminal.app
    // Terminal.app 默认以登录 shell 启动，PATH 会是完整的
    let script = format!(
        r#"tell application "Terminal"
            activate
            do script "cd '{}' && echo 'Starting Claude Code...' && {}"
        end tell"#,
        target_dir.replace("'", "'\\''"),
        command.replace("\"", "\\\"")
    );

    Command::new("osascript")
        .args(&["-e", &script])
        .spawn()
        .map_err(|e| format!("无法启动Terminal: {}", e))?;

    Ok(())
}
```

**检查 claude 命令**:

```rust
fn is_claude_available() -> bool {
    // 方法 1: claude --version
    if let Ok(output) = Command::new("claude").args(["--version"]).output() {
        if output.status.success() {
            return true;
        }
    }

    // 方法 2: npm list -g @anthropic-ai/claude-code
    if let Ok(output) = Command::new("npm")
        .args(["list", "-g", "@anthropic-ai/claude-code"])
        .output()
    {
        if output.status.success() {
            return true;
        }
    }

    false
}
```

#### 3.3.2 生成命令

**PowerShell 命令**:

```rust
pub fn generate_powershell_command(
    config: HashMap<String, String>
) -> Result<String, String> {
    let mut parts = Vec::new();

    for (key, value) in config {
        let escaped_value = value.replace("\"", "`\"");
        parts.push(format!("$env:{}=\"{}\"", key, escaped_value));
    }
    parts.push("claude".to_string());

    Ok(parts.join(";"))
}
```

**CMD 命令**:

```rust
pub fn generate_cmd_command(
    config: HashMap<String, String>
) -> Result<String, String> {
    let mut parts = Vec::new();

    for (key, value) in config {
        parts.push(format!("set {}={}", key, value));
    }
    parts.push("claude".to_string());

    Ok(parts.join(" & "))
}
```

**Bash 命令** (macOS/Linux/Git Bash):

```rust
pub fn generate_bash_command(config: &HashMap<String, String>) -> String {
    let mut parts = Vec::new();

    for (key, value) in config {
        // Bash 内联环境变量格式: KEY="value"
        let escaped_value = value.replace("\"", "\\\"");
        parts.push(format!("{}=\"{}\"", key, escaped_value));
    }

    // 添加 claude 命令
    parts.push("claude".to_string());

    // 如果启用了 skip_permissions，添加参数
    // 注意：skip_permissions 的处理在调用层
    parts.join(" ")
}
```

**示例输出**:

```powershell
# PowerShell
$env:ANTHROPIC_MODEL="qwen3-coder-480b-a35b";$env:ANTHROPIC_BASE_URL="http://api.url";claude --dangerously-skip-permissions

# CMD
set ANTHROPIC_MODEL=qwen3-coder-480b-a35b & set ANTHROPIC_BASE_URL=http://api.url & claude --dangerously-skip-permissions

# Bash
ANTHROPIC_MODEL="qwen3-coder-480b-a35b" ANTHROPIC_BASE_URL="http://api.url" claude --dangerously-skip-permissions
```

---

### 3.4 settings_manager.rs - Claude 设置管理

#### 3.4.1 配置文件路径

```rust
fn get_settings_path() -> Result<PathBuf, String> {
    let home_dir = dirs::home_dir()
        .ok_or("无法获取用户主目录".to_string())?;

    let settings_path = home_dir.join(".claude").join("settings.json");

    Ok(settings_path)
}
```

#### 3.4.2 保存配置

```rust
use serde_json::Value;
use std::collections::HashMap;
use std::fs;

pub fn save_config(config: HashMap<String, String>) -> Result<(), String> {
    let settings_path = get_settings_path()?;

    // 检查 .claude 目录是否存在
    let claude_dir = settings_path.parent().unwrap();
    if !claude_dir.exists() {
        return Err("Claude Code 未初始化，请先运行 'claude' 命令".to_string());
    }

    // 读取现有配置
    let mut settings: Value = if settings_path.exists() {
        let content = fs::read_to_string(&settings_path)
            .map_err(|e| format!("读取配置文件失败: {}", e))?;

        serde_json::from_str(&content)
            .map_err(|e| format!("解析配置文件失败: {}", e))?
    } else {
        // 创建新配置对象
        serde_json::json!({})
    };

    // 合并到 env 字段
    let env = settings
        .as_object_mut()
        .unwrap()
        .entry("env")
        .or_insert(serde_json::json!({}));

    let env_obj = env.as_object_mut().unwrap();
    for (key, value) in config {
        env_obj.insert(key, Value::String(value));
    }

    // 格式化写入
    let json_string = serde_json::to_string_pretty(&settings)
        .map_err(|e| format!("序列化配置失败: {}", e))?;

    fs::write(&settings_path, json_string)
        .map_err(|e| format!("写入配置文件失败: {}", e))?;

    Ok(())
}
```

#### 3.4.3 重置配置

```rust
pub fn reset_config() -> Result<(), String> {
    let settings_path = get_settings_path()?;

    if !settings_path.exists() {
        return Ok(()); // 文件不存在，无需重置
    }

    // 读取配置
    let content = fs::read_to_string(&settings_path)
        .map_err(|e| format!("读取配置文件失败: {}", e))?;

    let mut settings: Value = serde_json::from_str(&content)
        .map_err(|e| format!("解析配置文件失败: {}", e))?;

    // 删除相关环境变量
    if let Some(env) = settings.get_mut("env") {
        if let Some(env_obj) = env.as_object_mut() {
            // 删除 ANTHROPIC_* 和代理设置
            env_obj.remove("ANTHROPIC_MODEL");
            env_obj.remove("ANTHROPIC_BASE_URL");
            env_obj.remove("ANTHROPIC_AUTH_TOKEN");
            env_obj.remove("HTTP_PROXY");
            env_obj.remove("HTTPS_PROXY");

            // 如果 env 为空，删除整个字段
            if env_obj.is_empty() {
                settings.as_object_mut().unwrap().remove("env");
            }
        }
    }

    // 如果配置为空，删除文件
    if settings.as_object().unwrap().is_empty() {
        fs::remove_file(&settings_path)
            .map_err(|e| format!("删除配置文件失败: {}", e))?;
        return Ok(());
    }

    // 写回配置
    let json_string = serde_json::to_string_pretty(&settings)
        .map_err(|e| format!("序列化配置失败: {}", e))?;

    fs::write(&settings_path, json_string)
        .map_err(|e| format!("写入配置文件失败: {}", e))?;

    Ok(())
}
```

#### 3.4.4 打开设置文件

```rust
pub fn open_settings_file() -> Result<(), String> {
    let settings_path = get_settings_path()?;

    if !settings_path.exists() {
        return Err("设置文件不存在".to_string());
    }

    // 使用默认编辑器打开
    #[cfg(windows)]
    {
        Command::new("cmd")
            .args(["/C", "start", "", settings_path.to_str().unwrap()])
            .spawn()
            .map_err(|e| format!("打开文件失败: {}", e))?;
    }

    #[cfg(not(windows))]
    {
        Command::new("open")
            .arg(settings_path)
            .spawn()
            .map_err(|e| format!("打开文件失败: {}", e))?;
    }

    Ok(())
}
```

---

### 3.5 config_storage.rs - 应用配置存储

#### 3.5.1 数据结构

```rust
use serde::{Deserialize, Serialize};

fn default_skip_permissions() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub mode: String,       // "claude" | "custom"
    pub proxy: String,
    pub model: String,
    pub base_url: String,
    pub token: String,
    #[serde(default = "default_skip_permissions")]
    pub skip_permissions: bool,  // 是否跳过权限确认
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            mode: "claude".to_string(),
            proxy: String::new(),
            model: "qwen3-coder-480b-a35b".to_string(),
            base_url: "http://litellm.uattest.weoa.com".to_string(),
            token: String::new(),
            skip_permissions: true,  // 默认启用
        }
    }
}
```

**字段说明**:

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | `String` | `"claude"` | 工作模式 |
| `proxy` | `String` | `""` | 代理地址 |
| `model` | `String` | `"qwen3-coder-480b-a35b"` | 模型名称 |
| `base_url` | `String` | `"http://..."` | API 地址 |
| `token` | `String` | `""` | 认证令牌 |
| `skip_permissions` | `bool` | `true` | 跳过权限确认 |

**`#[serde(default = "...")]`**: 当 JSON 中缺少该字段时使用默认值，保持向后兼容

#### 3.5.2 配置文件路径

```rust
use std::path::PathBuf;

fn get_config_path() -> Result<PathBuf, String> {
    // 跨平台配置目录:
    // Windows: C:\Users\<user>\AppData\Roaming\ClaudeCodeLauncher
    // macOS: ~/Library/Application Support/ClaudeCodeLauncher
    // Linux: ~/.config/ClaudeCodeLauncher
    let config_dir = dirs::config_dir()
        .ok_or("无法获取配置目录".to_string())?
        .join("ClaudeCodeLauncher");

    // 确保目录存在
    if !config_dir.exists() {
        std::fs::create_dir_all(&config_dir)
            .map_err(|e| format!("创建配置目录失败: {}", e))?;
    }

    Ok(config_dir.join("config.json"))
}
```

**跨平台路径说明**:

| 平台 | 配置文件路径 |
|------|-------------|
| Windows | `C:\Users\<user>\AppData\Roaming\ClaudeCodeLauncher\config.json` |
| macOS | `~/Library/Application Support/ClaudeCodeLauncher/config.json` |
| Linux | `~/.config/ClaudeCodeLauncher/config.json` |

#### 3.5.3 保存配置

```rust
use base64::{Engine as _, engine::general_purpose};

pub fn save_config(config: &AppConfig) -> Result<(), String> {
    let config_path = get_config_path()?;

    // Token 使用 Base64 编码存储（简单混淆）
    let mut config_to_save = config.clone();
    if !config_to_save.token.is_empty() {
        config_to_save.token = general_purpose::STANDARD
            .encode(config_to_save.token.as_bytes());
    }

    // 序列化为 JSON
    let json_string = serde_json::to_string_pretty(&config_to_save)
        .map_err(|e| format!("序列化配置失败: {}", e))?;

    // 写入文件
    std::fs::write(&config_path, json_string)
        .map_err(|e| format!("写入配置失败: {}", e))?;

    Ok(())
}
```

#### 3.5.4 加载配置

```rust
pub fn load_config() -> Result<AppConfig, String> {
    let config_path = get_config_path()?;

    if !config_path.exists() {
        // 文件不存在，返回默认配置
        return Ok(AppConfig::default());
    }

    // 读取文件
    let content = std::fs::read_to_string(&config_path)
        .map_err(|e| format!("读取配置失败: {}", e))?;

    // 解析 JSON
    let mut config: AppConfig = serde_json::from_str(&content)
        .map_err(|e| format!("解析配置失败: {}", e))?;

    // 解码 Token
    if !config.token.is_empty() {
        match general_purpose::STANDARD.decode(config.token.as_bytes()) {
            Ok(decoded) => {
                config.token = String::from_utf8_lossy(&decoded).to_string();
            }
            Err(_) => {
                // 解码失败，保持原值（可能是未编码的旧配置）
                eprintln!("Token 解码失败，保持原值");
            }
        }
    }

    Ok(config)
}
```

---

### 3.6 environment.rs - 环境变量管理

#### 3.6.1 设置永久环境变量

```rust
#[cfg(windows)]
pub fn set_permanent(key: &str, value: &str) -> Result<(), String> {
    use winreg::enums::*;
    use winreg::RegKey;
    use windows::Win32::UI::WindowsAndMessaging::{
        SendMessageTimeoutW, HWND_BROADCAST, SMTO_ABORTIFHUNG, WM_SETTINGCHANGE,
    };

    // 1. 打开用户环境变量注册表键
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    let env_key = hkcu
        .open_subkey_with_flags("Environment", KEY_READ | KEY_WRITE)
        .map_err(|e| format!("打开注册表键失败: {}", e))?;

    // 2. 设置或删除环境变量
    if value.is_empty() {
        // 空值表示删除
        env_key
            .delete_value(key)
            .map_err(|e| format!("删除环境变量失败: {}", e))?;
    } else {
        // 设置环境变量
        env_key
            .set_value(key, &value)
            .map_err(|e| format!("设置环境变量失败: {}", e))?;
    }

    // 3. 广播 WM_SETTINGCHANGE 消息通知系统
    unsafe {
        let _ = SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            None,
            Some("Environment"),
            SMTO_ABORTIFHUNG,
            5000,
            None,
        );
    }

    Ok(())
}
```

#### 3.6.2 批量设置环境变量

```rust
pub fn set_environment_variables(
    config: std::collections::HashMap<String, String>
) -> Result<(), String> {
    for (key, value) in config {
        set_permanent(&key, &value)?;
    }
    Ok(())
}
```

#### 3.6.3 获取支持的环境变量

```rust
pub fn get_env_keys() -> Vec<String> {
    vec![
        "ANTHROPIC_MODEL".to_string(),
        "ANTHROPIC_BASE_URL".to_string(),
        "ANTHROPIC_AUTH_TOKEN".to_string(),
        "HTTP_PROXY".to_string(),
        "HTTPS_PROXY".to_string(),
    ]
}
```

---

## 4. Commands 层

### 4.1 Commands 定义 (commands/mod.rs)

```rust
use crate::services::*;
use std::collections::HashMap;

// ============ 依赖检测 Commands ============

#[tauri::command]
pub fn check_nodejs() -> dependency_checker::DependencyStatus {
    dependency_checker::check_nodejs()
}

#[tauri::command]
pub fn check_claude() -> dependency_checker::DependencyStatus {
    dependency_checker::check_claude()
}

#[tauri::command]
pub async fn check_nodejs_with_update() -> dependency_checker::DependencyStatus {
    dependency_checker::check_nodejs_with_update()
}

#[tauri::command]
pub async fn check_claude_with_update() -> dependency_checker::DependencyStatus {
    dependency_checker::check_claude_with_update().await
}

#[tauri::command]
pub fn refresh_system_path() -> Result<(), String> {
    dependency_checker::refresh_system_path()
}

// ============ 安装/更新 Commands ============

#[tauri::command]
pub fn install_nodejs() -> Result<(), String> {
    installer::install_nodejs()
}

#[tauri::command]
pub fn update_nodejs() -> Result<(), String> {
    installer::update_nodejs()
}

#[tauri::command]
pub fn install_claude() -> Result<(), String> {
    installer::install_claude()
}

#[tauri::command]
pub fn update_claude() -> Result<(), String> {
    installer::update_claude()
}

// ============ 启动器 Commands ============

#[tauri::command]
pub fn launch_claude_code(config: HashMap<String, String>) -> Result<(), String> {
    launcher::launch_with_config(config)
}

#[tauri::command]
pub fn generate_powershell_command(config: HashMap<String, String>) -> Result<String, String> {
    launcher::generate_powershell_command(config)
}

#[tauri::command]
pub fn generate_cmd_command(config: HashMap<String, String>) -> Result<String, String> {
    launcher::generate_cmd_command(config)
}

// ============ 设置管理 Commands ============

#[tauri::command]
pub fn save_to_settings(config: HashMap<String, String>) -> Result<(), String> {
    settings_manager::save_config(config)
}

#[tauri::command]
pub fn reset_settings() -> Result<(), String> {
    settings_manager::reset_config()
}

#[tauri::command]
pub fn open_settings_file() -> Result<(), String> {
    settings_manager::open_settings_file()
}

// ============ 应用配置 Commands ============

#[tauri::command]
pub fn save_app_config(config: config_storage::AppConfig) -> Result<(), String> {
    config_storage::save_config(&config)
}

#[tauri::command]
pub fn load_app_config() -> Result<config_storage::AppConfig, String> {
    config_storage::load_config()
}

// ============ 桥接管理 Commands ============

#[tauri::command]
pub fn get_hostname() -> String {
    // 优先读取 ~/.agent-bridge/client_id，回退到 COMPUTERNAME/HOSTNAME
    if let Some(home) = dirs::home_dir() {
        let id_file = home.join(".agent-bridge").join("client_id");
        if let Ok(id) = std::fs::read_to_string(&id_file) {
            let id = id.trim().to_string();
            if !id.is_empty() { return id; }
        }
    }
    std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_else(|_| "unknown".to_string())
}

#[tauri::command]
pub fn get_username() -> String {
    // 获取系统用户名并转小写
    std::env::var("USERNAME")
        .or_else(|_| std::env::var("USER"))
        .unwrap_or_else(|_| "unknown".to_string())
        .to_lowercase()
}

#[tauri::command]
pub async fn bridge_get_or_create_key(username: String) -> Result<String, String> {
    // 使用 .no_proxy() 绕过系统代理
    let client = reqwest::Client::builder().no_proxy().build()
        .map_err(|e| format!("HTTP 客户端初始化失败: {}", e))?;
    // 1. POST /api/login 获取 admin_token Cookie
    // 2. GET /api/admin/users/{username} 查询已有用户
    // 3. 如果 404，POST /api/admin/users 创建新用户
    // 4. 返回 api_key
    // ...
}
```

### 4.2 注册 Commands (lib.rs)

```rust
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            commands::check_nodejs,
            commands::check_claude,
            commands::check_nodejs_with_update,
            commands::check_claude_with_update,
            commands::refresh_system_path,
            commands::install_nodejs,
            commands::update_nodejs,
            commands::install_claude,
            commands::update_claude,
            commands::launch_claude_code,
            commands::generate_powershell_command,
            commands::generate_cmd_command,
            commands::save_to_settings,
            commands::reset_settings,
            commands::open_settings_file,
            commands::save_app_config,
            commands::load_app_config,
            // Bridge admin API commands
            commands::get_hostname,
            commands::get_username,
            commands::bridge_get_or_create_key,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

---

## 5. 系统集成

### 5.1 Windows 注册表操作

**读取注册表值**:

```rust
use winreg::enums::*;
use winreg::RegKey;

let hkcu = RegKey::predef(HKEY_CURRENT_USER);
let key = hkcu.open_subkey("Environment")?;
let value: String = key.get_value("Path")?;
```

**写入注册表值**:

```rust
let hkcu = RegKey::predef(HKEY_CURRENT_USER);
let key = hkcu.open_subkey_with_flags("Environment", KEY_WRITE)?;
key.set_value("MY_VAR", &"my_value")?;
```

**删除注册表值**:

```rust
key.delete_value("MY_VAR")?;
```

### 5.2 进程创建

**普通进程**:

```rust
use std::process::Command;

let output = Command::new("node")
    .args(["--version"])
    .output()?;
```

**新控制台窗口** (Windows):

```rust
use std::os::windows::process::CommandExt;
use windows::Win32::System::Threading::CREATE_NEW_CONSOLE;

Command::new("powershell")
    .args(["-Command", "echo Hello"])
    .creation_flags(CREATE_NEW_CONSOLE.0)
    .spawn()?;
```

**带工作目录**:

```rust
Command::new("claude")
    .current_dir("/path/to/dir")
    .spawn()?;
```

### 5.3 文件系统操作

**读取文件**:

```rust
let content = std::fs::read_to_string("config.json")?;
```

**写入文件**:

```rust
std::fs::write("config.json", "content")?;
```

**创建目录**:

```rust
std::fs::create_dir_all("/path/to/dir")?;
```

**检查存在**:

```rust
if std::path::Path::new("file.txt").exists() {
    // ...
}
```

### 5.4 HTTP 请求

**GET 请求**:

```rust
let response = reqwest::get("https://api.example.com/data").await?;
let json: serde_json::Value = response.json().await?;
```

**带超时**:

```rust
let client = reqwest::Client::builder()
    .timeout(Duration::from_secs(10))
    .build()?;

let response = client.get("https://api.example.com").send().await?;
```

---

## 6. 错误处理

### 6.1 错误类型

**Result 类型**:

```rust
pub fn some_function() -> Result<String, String> {
    // 成功
    Ok("result".to_string())

    // 失败
    Err("error message".to_string())
}
```

**错误传播**:

```rust
pub fn outer_function() -> Result<(), String> {
    // ? 操作符自动传播错误
    let result = inner_function()?;

    // map_err 转换错误类型
    let file = std::fs::read_to_string("file.txt")
        .map_err(|e| format!("读取文件失败: {}", e))?;

    Ok(())
}
```

### 6.2 错误处理模式

**模式 1: 返回详细错误**:

```rust
pub fn function() -> Result<T, String> {
    match some_operation() {
        Ok(result) => Ok(result),
        Err(e) => Err(format!("操作失败: {}", e)),
    }
}
```

**模式 2: 提供备选方案**:

```rust
pub fn check_dependency() -> DependencyStatus {
    // 尝试方法 1
    if let Ok(result) = method1() {
        return result;
    }

    // 失败后尝试方法 2
    if let Ok(result) = method2() {
        return result;
    }

    // 都失败，返回默认状态
    DependencyStatus::default()
}
```

**模式 3: 日志记录**:

```rust
pub fn function() -> Result<(), String> {
    match operation() {
        Ok(_) => Ok(()),
        Err(e) => {
            eprintln!("操作失败: {}", e);  // 输出到 stderr
            Err(format!("操作失败: {}", e))
        }
    }
}
```

### 6.3 错误信息国际化

**中文错误提示**:

```rust
match error_type {
    NotFound => "文件未找到",
    PermissionDenied => "权限被拒绝",
    AlreadyExists => "文件已存在",
    _ => "未知错误",
}
```

---

## 7. 开发实践

### 7.1 跨平台条件编译

**平台条件编译属性**:

```rust
// 仅 Windows
#[cfg(windows)]
fn windows_only_function() { /* ... */ }

// 仅 macOS
#[cfg(target_os = "macos")]
fn macos_only_function() { /* ... */ }

// 仅 Linux
#[cfg(target_os = "linux")]
fn linux_only_function() { /* ... */ }

// 非 Windows
#[cfg(not(windows))]
fn non_windows_function() { /* ... */ }

// 多平台
#[cfg(any(windows, target_os = "macos"))]
fn windows_or_macos_function() { /* ... */ }
```

**平台检测函数**:

```rust
#[tauri::command]
pub fn get_platform() -> String {
    #[cfg(windows)]
    return "windows".to_string();

    #[cfg(target_os = "macos")]
    return "macos".to_string();

    #[cfg(target_os = "linux")]
    return "linux".to_string();

    #[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
    return "unknown".to_string();
}
```

**跨平台安装示例**:

```rust
pub fn install_gitbash() -> Result<(), String> {
    #[cfg(windows)]
    {
        // Windows: 使用 winget
        execute_powershell_in_new_window(r#"
            Write-Host "正在安装 Git..." -ForegroundColor Green
            winget install Git.Git
        "#)
    }

    #[cfg(target_os = "macos")]
    {
        // macOS: 使用 Homebrew
        execute_in_terminal(r#"
            echo "正在安装 Git..."
            brew install git
        "#)
    }

    #[cfg(not(any(windows, target_os = "macos")))]
    {
        Err("当前平台不支持自动安装".to_string())
    }
}
```

---

### 7.2 最佳实践

**1. 模块化设计**:
- ✅ 每个服务模块专注单一领域
- ✅ 服务之间通过公开接口交互
- ✅ 避免循环依赖

**2. 错误处理**:
- ✅ 使用 `Result` 类型明确错误
- ✅ 提供详细的错误信息
- ✅ 记录错误日志便于调试

**3. 类型安全**:
- ✅ 使用强类型而非字符串传递数据
- ✅ 定义清晰的数据结构
- ✅ 利用 Serde 实现序列化

**4. 平台兼容**:
- ✅ 使用 `#[cfg(windows)]` / `#[cfg(target_os = "macos")]` 条件编译
- ✅ 跨平台代码使用抽象
- ✅ 提供平台特定实现
- ✅ 使用 `get_platform()` 进行运行时平台检测

### 7.2 常见模式

**模式 1: Builder 模式**:

```rust
Command::new("powershell")
    .args(["-Command", "echo hello"])
    .current_dir("/path")
    .spawn()?;
```

**模式 2: 链式调用**:

```rust
let result = some_function()
    .map(|x| x * 2)
    .map_err(|e| format!("错误: {}", e))?;
```

**模式 3: 迭代器**:

```rust
let result: Vec<_> = paths
    .iter()
    .filter(|p| !p.is_empty())
    .map(|p| p.to_uppercase())
    .collect();
```

### 7.3 性能优化

**1. 避免不必要的克隆**:

```rust
// ❌ 不好
fn process(data: String) { /* ... */ }

// ✅ 更好
fn process(data: &str) { /* ... */ }
```

**2. 使用引用而非所有权**:

```rust
// ❌ 不好
fn print_config(config: AppConfig) {
    println!("{:?}", config);
}

// ✅ 更好
fn print_config(config: &AppConfig) {
    println!("{:?}", config);
}
```

**3. 预分配容量**:

```rust
let mut vec = Vec::with_capacity(100);
let mut map = HashMap::with_capacity(50);
```

### 7.4 调试技巧

**1. 打印调试**:

```rust
eprintln!("变量值: {:?}", variable);
eprintln!("执行到此处");
```

**2. 使用 Debug trait**:

```rust
#[derive(Debug)]
struct MyStruct {
    field: String,
}

let s = MyStruct { field: "test".to_string() };
eprintln!("{:?}", s);  // MyStruct { field: "test" }
```

**3. 条件编译调试代码**:

```rust
#[cfg(debug_assertions)]
{
    eprintln!("调试信息");
}
```

### 7.5 测试

**单元测试**:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version_compare() {
        assert_eq!(compare_versions("2.0.0", "1.0.0"), 1);
        assert_eq!(compare_versions("1.0.0", "2.0.0"), -1);
        assert_eq!(compare_versions("1.0.0", "1.0.0"), 0);
    }
}
```

**运行测试**:

```bash
cargo test
```

---

## 8. 总结

### 8.1 后端架构特点

- 🦀 **Rust 类型安全**: 编译期错误检查
- ⚡ **高性能**: 零成本抽象，无 GC
- 🔧 **系统级集成**: Windows 和 macOS API 深度集成
- 📦 **模块化设计**: 清晰的职责划分
- 🛡️ **错误处理**: Result 类型明确错误
- 🖥️ **跨平台**: 条件编译支持多平台

### 8.2 技术亮点

- ✨ Tauri 2 现代框架
- ✨ Tokio 异步运行时
- ✨ Windows 和 macOS 条件编译
- ✨ 注册表和环境变量管理
- ✨ 多方法依赖检测 (Node.js/Claude Code/Git Bash)
- ✨ 多 Shell 命令生成 (PowerShell/CMD/Bash)
- ✨ 跳过权限确认模式 (`--dangerously-skip-permissions`)

### 8.3 API 统计

| 类型 | 数量 |
|------|------|
| 依赖检测 | 7 |
| 安装/更新 | 6 |
| 启动器 | 4 |
| 平台检测 | 1 |
| 设置管理 | 3 |
| 应用配置 | 2 |
| **总计** | **27** |

### 8.4 后续优化方向

- 🔮 支持 Linux 平台
- 🔮 添加自动更新功能
- 🔮 优化错误恢复机制
- 🔮 添加更多配置选项
- 🔮 性能监控和日志

---

**相关文档**:
- [项目总览](./PROJECT_DOCUMENTATION.md)
- [前端开发指南](./FRONTEND_GUIDE.md)
- [API 参考](./API_REFERENCE.md)
