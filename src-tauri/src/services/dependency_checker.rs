use serde::{Deserialize, Serialize};
use std::process::Command;
use regex::Regex;

#[cfg(target_os = "macos")]
use std::env;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// CREATE_NO_WINDOW flag for Windows — prevents console window flash
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// On Windows, configure a Command to hide the console window.
/// On other platforms, this is a no-op.
#[cfg(windows)]
fn hide_window(cmd: &mut Command) -> &mut Command {
    cmd.creation_flags(CREATE_NO_WINDOW)
}

#[cfg(not(windows))]
fn hide_window(cmd: &mut Command) -> &mut Command {
    cmd
}

/// Get extended PATH for macOS that includes common installation locations
/// This is needed because GUI apps don't inherit shell PATH from .zshrc/.bash_profile
#[cfg(target_os = "macos")]
pub fn get_macos_extended_path() -> String {
    let home = dirs::home_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| "".to_string());

    let mut extra_paths: Vec<String> = vec![
        "/usr/local/bin".to_string(),
        "/opt/homebrew/bin".to_string(),
        "/opt/homebrew/sbin".to_string(),
    ];

    if !home.is_empty() {
        extra_paths.push(format!("{}/.npm-global/bin", home));
        extra_paths.push(format!("{}/Library/pnpm", home));
        extra_paths.push(format!("{}/.local/bin", home));

        // Check for nvm installations - expand glob pattern manually
        let nvm_base = format!("{}/.nvm/versions/node", home);
        if let Ok(entries) = std::fs::read_dir(&nvm_base) {
            for entry in entries.flatten() {
                let bin_path = entry.path().join("bin");
                if bin_path.exists() {
                    extra_paths.push(bin_path.to_string_lossy().to_string());
                }
            }
        }

        // Check for fnm installations
        let fnm_base = format!("{}/Library/Application Support/fnm/node-versions", home);
        if let Ok(entries) = std::fs::read_dir(&fnm_base) {
            for entry in entries.flatten() {
                let bin_path = entry.path().join("installation/bin");
                if bin_path.exists() {
                    extra_paths.push(bin_path.to_string_lossy().to_string());
                }
            }
        }

        // Check for volta installations
        extra_paths.push(format!("{}/.volta/bin", home));
    }

    // Get current PATH and combine
    let current_path = env::var("PATH").unwrap_or_default();
    let mut all_paths: Vec<&str> = extra_paths.iter().map(|s| s.as_str()).collect();
    all_paths.extend(current_path.split(':'));

    all_paths.join(":")
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DependencyStatus {
    pub installed: bool,
    pub version: Option<String>,
    pub meets_requirement: bool,
    pub latest_version: Option<String>,
    pub update_available: bool,
    pub error: Option<String>,
}

pub struct DependencyChecker;

impl DependencyChecker {
    pub fn check_nodejs() -> DependencyStatus {
        #[cfg(target_os = "macos")]
        {
            // On macOS, use extended PATH to find node
            let extended_path = get_macos_extended_path();
            let output = Command::new("sh")
                .args(&["-c", &format!("PATH='{}' node --version", extended_path)])
                .output();

            match output {
                Ok(out) if out.status.success() => {
                    let stdout = String::from_utf8_lossy(&out.stdout);
                    if let Ok(re) = Regex::new(r"v(\d+\.\d+\.\d+)") {
                        if let Some(caps) = re.captures(&stdout) {
                            let version = caps.get(1).map(|m| m.as_str().to_string());
                            let meets_requirement = if let Some(ref v) = version {
                                Self::compare_versions(v, "18.0.0")
                            } else {
                                false
                            };
                            return DependencyStatus {
                                installed: true,
                                version,
                                meets_requirement,
                                latest_version: None,
                                update_available: false,
                                error: None,
                            };
                        }
                    }
                    DependencyStatus {
                        installed: true,
                        version: None,
                        meets_requirement: false,
                        latest_version: None,
                        update_available: false,
                        error: Some("无法解析版本号".to_string()),
                    }
                }
                _ => DependencyStatus {
                    installed: false,
                    version: None,
                    meets_requirement: false,
                    latest_version: None,
                    update_available: false,
                    error: Some("Node.js not found".to_string()),
                },
            }
        }

        #[cfg(windows)]
        {
            Self::refresh_system_path();
            let result = Self::check_dependency("node", &["--version"], r"v(\d+\.\d+\.\d+)", Some("18.0.0"));
            if result.installed {
                return result;
            }
            // Fallback: check known install path directly
            let node_exe = r"C:\Program Files\nodejs\node.exe";
            if std::path::Path::new(node_exe).exists() {
                let mut cmd = Command::new(node_exe);
                cmd.arg("--version");
                hide_window(&mut cmd);
                if let Ok(out) = cmd.output() {
                    if out.status.success() {
                        let stdout = String::from_utf8_lossy(&out.stdout);
                        if let Ok(re) = Regex::new(r"v(\d+\.\d+\.\d+)") {
                            if let Some(caps) = re.captures(&stdout) {
                                let version = caps.get(1).map(|m| m.as_str().to_string());
                                let meets_requirement = if let Some(ref v) = version {
                                    Self::compare_versions(v, "18.0.0")
                                } else {
                                    false
                                };
                                return DependencyStatus {
                                    installed: true,
                                    version,
                                    meets_requirement,
                                    latest_version: None,
                                    update_available: false,
                                    error: None,
                                };
                            }
                        }
                    }
                }
            }
            result
        }

        #[cfg(all(not(windows), not(target_os = "macos")))]
        Self::check_dependency("node", &["--version"], r"v(\d+\.\d+\.\d+)", Some("18.0.0"))
    }

    pub fn check_gitbash() -> DependencyStatus {
        #[cfg(windows)]
        {
            Self::refresh_system_path();
            let result = Self::check_dependency("git", &["--version"], r"git version (\d+\.\d+\.\d+)", None);
            if result.installed {
                return result;
            }
            // Fallback: check known install paths directly
            for git_exe in &[
                r"C:\Program Files\Git\cmd\git.exe",
                r"C:\Program Files (x86)\Git\cmd\git.exe",
            ] {
                if std::path::Path::new(git_exe).exists() {
                    // git.exe exists but not in PATH yet — could be mid-install.
                    // Inno Setup extracts git.exe before the installer finishes,
                    // so check if the installer is still running before reporting installed.
                    if Self::is_git_installer_running() {
                        log::info!("git.exe found at {} but installer still running, waiting...", git_exe);
                        break;
                    }
                    let mut cmd = Command::new(git_exe);
                    cmd.arg("--version");
                    hide_window(&mut cmd);
                    if let Ok(out) = cmd.output() {
                        if out.status.success() {
                            let stdout = String::from_utf8_lossy(&out.stdout);
                            if let Ok(re) = Regex::new(r"git version (\d+\.\d+\.\d+)") {
                                if let Some(caps) = re.captures(&stdout) {
                                    let version = caps.get(1).map(|m| m.as_str().to_string());
                                    return DependencyStatus {
                                        installed: true,
                                        version,
                                        meets_requirement: true,
                                        latest_version: None,
                                        update_available: false,
                                        error: None,
                                    };
                                }
                            }
                        }
                    }
                }
            }
            result
        }

        #[cfg(not(windows))]
        Self::check_dependency("git", &["--version"], r"git version (\d+\.\d+\.\d+)", None)
    }

    pub fn check_claude() -> DependencyStatus {
        #[cfg(windows)]
        Self::refresh_system_path();

        // 跨平台检测 claude
        #[cfg(windows)]
        let output = {
            let mut cmd = Command::new("cmd");
            cmd.args(&["/c", "claude", "--version"]);
            hide_window(&mut cmd);
            cmd.output()
        };

        #[cfg(target_os = "macos")]
        let output = {
            // On macOS, use extended PATH to find claude
            let extended_path = get_macos_extended_path();
            Command::new("sh")
                .args(&["-c", &format!("PATH='{}' claude --version", extended_path)])
                .output()
        };

        #[cfg(all(not(windows), not(target_os = "macos")))]
        let output = Command::new("claude")
            .arg("--version")
            .output();

        match output {
            Ok(out) if out.status.success() => {
                let stdout = String::from_utf8_lossy(&out.stdout);

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
                                latest_version: None,
                                update_available: false,
                                error: None,
                            };
                        }
                    }
                }

                DependencyStatus {
                    installed: true,
                    version: None,
                    meets_requirement: true,
                    latest_version: None,
                    update_available: false,
                    error: Some("无法解析版本号".to_string()),
                }
            }
            _ => {
                // claude --version failed. Auto-repair: reinstall if npm is available.
                #[cfg(windows)]
                {
                    let mut where_cmd = Command::new("cmd");
                    where_cmd.args(&["/c", "where", "npm"]);
                    hide_window(&mut where_cmd);
                    let npm_available = where_cmd.output()
                        .map(|o| o.status.success())
                        .unwrap_or(false);

                    if npm_available {
                        eprintln!("[check_claude] Windows: claude not found, attempting reinstall...");
                        let mut install_cmd = Command::new("cmd");
                        install_cmd.args(&["/c", "npm", "install", "-g", "@anthropic-ai/claude-code"]);
                        hide_window(&mut install_cmd);
                        let _ = install_cmd.output();

                        Self::refresh_system_path();

                        let mut retry_cmd = Command::new("cmd");
                        retry_cmd.args(&["/c", "claude", "--version"]);
                        hide_window(&mut retry_cmd);
                        let retry = retry_cmd.output();

                        if let Ok(out) = retry {
                            if out.status.success() {
                                let stdout = String::from_utf8_lossy(&out.stdout);
                                if let Ok(re) = Regex::new(r"(\d+\.\d+\.\d+)") {
                                    if let Some(caps) = re.captures(&stdout) {
                                        let version = caps.get(1).map(|m| m.as_str().to_string());
                                        return DependencyStatus {
                                            installed: true,
                                            version,
                                            meets_requirement: true,
                                            latest_version: None,
                                            update_available: false,
                                            error: None,
                                        };
                                    }
                                }
                            }
                        }
                    }
                }

                #[cfg(target_os = "macos")]
                {
                    let extended_path = get_macos_extended_path();

                    let npm_available = Command::new("sh")
                        .args(&["-c", &format!("PATH='{}' which npm", extended_path)])
                        .output()
                        .map(|o| o.status.success())
                        .unwrap_or(false);

                    if npm_available {
                        eprintln!("[check_claude] macOS: claude not found, attempting reinstall...");
                        let _ = Command::new("sh")
                            .args(&["-c", &format!("PATH='{}' npm install -g @anthropic-ai/claude-code", extended_path)])
                            .output();

                        let retry = Command::new("sh")
                            .args(&["-c", &format!("PATH='{}' claude --version", extended_path)])
                            .output();

                        if let Ok(out) = retry {
                            if out.status.success() {
                                let stdout = String::from_utf8_lossy(&out.stdout);
                                if let Ok(re) = Regex::new(r"(\d+\.\d+\.\d+)") {
                                    if let Some(caps) = re.captures(&stdout) {
                                        let version = caps.get(1).map(|m| m.as_str().to_string());
                                        return DependencyStatus {
                                            installed: true,
                                            version,
                                            meets_requirement: true,
                                            latest_version: None,
                                            update_available: false,
                                            error: None,
                                        };
                                    }
                                }
                            }
                        }
                    }
                }

                DependencyStatus {
                    installed: false,
                    version: None,
                    meets_requirement: false,
                    latest_version: None,
                    update_available: false,
                    error: Some("Claude Code not found".to_string()),
                }
            },
        }
    }

    pub fn check_codex() -> DependencyStatus {
        #[cfg(windows)]
        Self::refresh_system_path();

        #[cfg(windows)]
        let output = {
            let mut cmd = Command::new("cmd");
            cmd.args(&["/c", "codex", "--version"]);
            hide_window(&mut cmd);
            cmd.output()
        };

        #[cfg(target_os = "macos")]
        let output = {
            let extended_path = get_macos_extended_path();
            Command::new("sh")
                .args(&["-c", &format!("PATH='{}' codex --version", extended_path)])
                .output()
        };

        #[cfg(all(not(windows), not(target_os = "macos")))]
        let output = Command::new("codex")
            .arg("--version")
            .output();

        match output {
            Ok(out) if out.status.success() => {
                let stdout = String::from_utf8_lossy(&out.stdout);
                let stderr = String::from_utf8_lossy(&out.stderr);
                let combined = format!("{}{}", stdout, stderr);

                if let Ok(re) = Regex::new(r"(\d+\.\d+\.\d+)") {
                    if let Some(caps) = re.captures(&combined) {
                        let version = caps.get(1).map(|m| m.as_str().to_string());
                        return DependencyStatus {
                            installed: true,
                            version,
                            meets_requirement: true,
                            latest_version: None,
                            update_available: false,
                            error: None,
                        };
                    }
                }

                DependencyStatus {
                    installed: true,
                    version: None,
                    meets_requirement: true,
                    latest_version: None,
                    update_available: false,
                    error: Some("无法解析版本号".to_string()),
                }
            }
            _ => {
                // codex --version failed. Auto-repair: reinstall if npm is available.
                #[cfg(windows)]
                {
                    let mut where_cmd = Command::new("cmd");
                    where_cmd.args(&["/c", "where", "npm"]);
                    hide_window(&mut where_cmd);
                    let npm_available = where_cmd.output()
                        .map(|o| o.status.success())
                        .unwrap_or(false);

                    if npm_available {
                        eprintln!("[check_codex] Windows: codex not found, attempting reinstall...");
                        let mut install_cmd = Command::new("cmd");
                        install_cmd.args(&["/c", "npm", "install", "-g", "@openai/codex"]);
                        hide_window(&mut install_cmd);
                        let _ = install_cmd.output();

                        Self::refresh_system_path();

                        let mut retry_cmd = Command::new("cmd");
                        retry_cmd.args(&["/c", "codex", "--version"]);
                        hide_window(&mut retry_cmd);
                        let retry = retry_cmd.output();

                        if let Ok(out) = retry {
                            if out.status.success() {
                                let stdout = String::from_utf8_lossy(&out.stdout);
                                let stderr = String::from_utf8_lossy(&out.stderr);
                                let combined = format!("{}{}", stdout, stderr);
                                if let Ok(re) = Regex::new(r"(\d+\.\d+\.\d+)") {
                                    if let Some(caps) = re.captures(&combined) {
                                        let version = caps.get(1).map(|m| m.as_str().to_string());
                                        return DependencyStatus {
                                            installed: true,
                                            version,
                                            meets_requirement: true,
                                            latest_version: None,
                                            update_available: false,
                                            error: None,
                                        };
                                    }
                                }
                            }
                        }
                    }
                }

                #[cfg(target_os = "macos")]
                {
                    let extended_path = get_macos_extended_path();

                    let npm_available = Command::new("sh")
                        .args(&["-c", &format!("PATH='{}' which npm", extended_path)])
                        .output()
                        .map(|o| o.status.success())
                        .unwrap_or(false);

                    if npm_available {
                        eprintln!("[check_codex] macOS: codex not found, attempting reinstall...");
                        let _ = Command::new("sh")
                            .args(&["-c", &format!("PATH='{}' npm install -g @openai/codex", extended_path)])
                            .output();

                        let retry = Command::new("sh")
                            .args(&["-c", &format!("PATH='{}' codex --version", extended_path)])
                            .output();

                        if let Ok(out) = retry {
                            if out.status.success() {
                                let stdout = String::from_utf8_lossy(&out.stdout);
                                let stderr = String::from_utf8_lossy(&out.stderr);
                                let combined = format!("{}{}", stdout, stderr);
                                if let Ok(re) = Regex::new(r"(\d+\.\d+\.\d+)") {
                                    if let Some(caps) = re.captures(&combined) {
                                        let version = caps.get(1).map(|m| m.as_str().to_string());
                                        return DependencyStatus {
                                            installed: true,
                                            version,
                                            meets_requirement: true,
                                            latest_version: None,
                                            update_available: false,
                                            error: None,
                                        };
                                    }
                                }
                            }
                        }
                    }
                }

                DependencyStatus {
                    installed: false,
                    version: None,
                    meets_requirement: false,
                    latest_version: None,
                    update_available: false,
                    error: Some("Codex CLI not found".to_string()),
                }
            },
        }
    }

    fn check_dependency(
        command: &str,
        args: &[&str],
        pattern: &str,
        min_version: Option<&str>,
    ) -> DependencyStatus {
        let mut cmd = Command::new(command);
        cmd.args(args);
        hide_window(&mut cmd);
        let output = cmd.output();

        match output {
            Ok(out) if out.status.success() => {
                let stdout = String::from_utf8_lossy(&out.stdout);
                let re = Regex::new(pattern).unwrap();

                if let Some(caps) = re.captures(&stdout) {
                    let version = caps.get(1).map(|m| m.as_str().to_string());

                    let meets_requirement = if let (Some(ref v), Some(min)) = (&version, min_version) {
                        Self::compare_versions(v, min)
                    } else {
                        true
                    };

                    DependencyStatus {
                        installed: true,
                        version,
                        meets_requirement,
                        latest_version: None,
                        update_available: false,
                        error: None,
                    }
                } else {
                    DependencyStatus {
                        installed: false,
                        version: None,
                        meets_requirement: false,
                        latest_version: None,
                        update_available: false,
                        error: Some("无法解析版本号".to_string()),
                    }
                }
            }
            Ok(_) => DependencyStatus {
                installed: false,
                version: None,
                meets_requirement: false,
                latest_version: None,
                update_available: false,
                error: Some("命令执行失败".to_string()),
            },
            Err(e) => DependencyStatus {
                installed: false,
                version: None,
                meets_requirement: false,
                latest_version: None,
                update_available: false,
                error: Some(format!("Not installed: {}", e)),
            },
        }
    }

    pub async fn check_nodejs_with_update() -> DependencyStatus {
        let mut status = Self::check_nodejs();
        if status.installed {
            status.latest_version = Self::get_nodejs_latest_version().await;
            if let (Some(ref current), Some(ref latest)) = (&status.version, &status.latest_version) {
                status.update_available = !Self::compare_versions(current, latest);
            }
        }
        status
    }

    pub async fn check_claude_with_update() -> DependencyStatus {
        let mut status = Self::check_claude();
        if status.installed {
            status.latest_version = Self::get_claude_latest_version().await;
            if let (Some(ref current), Some(ref latest)) = (&status.version, &status.latest_version) {
                status.update_available = !Self::compare_versions(current, latest);
            }
        }
        status
    }

    pub async fn check_codex_with_update() -> DependencyStatus {
        let mut status = Self::check_codex();
        if status.installed {
            status.latest_version = Self::get_codex_latest_version().await;
            if let (Some(ref current), Some(ref latest)) = (&status.version, &status.latest_version) {
                status.update_available = !Self::compare_versions(current, latest);
            }
        }
        status
    }

    pub async fn check_gitbash_with_update() -> DependencyStatus {
        let mut status = Self::check_gitbash();
        if status.installed {
            // On macOS, skip update check for Apple Git — it's managed by macOS/Xcode
            // and comparing against Homebrew's latest version is misleading.
            #[cfg(target_os = "macos")]
            {
                let is_apple_git = Command::new("git")
                    .args(&["--version"])
                    .output()
                    .map(|o| String::from_utf8_lossy(&o.stdout).contains("Apple Git"))
                    .unwrap_or(false);

                if !is_apple_git {
                    status.latest_version = Self::get_gitbash_latest_version().await;
                    if let (Some(ref current), Some(ref latest)) = (&status.version, &status.latest_version) {
                        status.update_available = !Self::compare_versions(current, latest);
                    }
                }
            }

            #[cfg(not(target_os = "macos"))]
            {
                status.latest_version = Self::get_gitbash_latest_version().await;
                if let (Some(ref current), Some(ref latest)) = (&status.version, &status.latest_version) {
                    status.update_available = !Self::compare_versions(current, latest);
                }
            }
        }
        status
    }

    fn compare_versions(version1: &str, version2: &str) -> bool {
        let v1_parts: Vec<u32> = version1
            .split('.')
            .filter_map(|s| s.parse().ok())
            .collect();
        let v2_parts: Vec<u32> = version2
            .split('.')
            .filter_map(|s| s.parse().ok())
            .collect();

        let max_len = v1_parts.len().max(v2_parts.len());

        for i in 0..max_len {
            let v1 = v1_parts.get(i).copied().unwrap_or(0);
            let v2 = v2_parts.get(i).copied().unwrap_or(0);

            if v1 > v2 {
                return true;
            } else if v1 < v2 {
                return false;
            }
        }

        true
    }

    async fn get_nodejs_latest_version() -> Option<String> {
        #[cfg(windows)]
        {
            // Windows: 先尝试 winget，失败则从 npmmirror 获取
            for attempt in 0..3 {
                let mut cmd = tokio::process::Command::new("winget");
                cmd.args(&["show", "OpenJS.NodeJS.LTS"]);
                #[cfg(windows)]
                cmd.creation_flags(CREATE_NO_WINDOW);
                if let Ok(output) = cmd.output().await
                {
                    if output.status.success() {
                        let stdout = String::from_utf8_lossy(&output.stdout);

                        if let Some(caps) = Regex::new(r"版本:\s*(\d+\.\d+\.\d+)").unwrap().captures(&stdout) {
                            if let Some(version) = caps.get(1) {
                                return Some(version.as_str().to_string());
                            }
                        }

                        if let Some(caps) = Regex::new(r"Version:\s*(\d+\.\d+\.\d+)").unwrap().captures(&stdout) {
                            if let Some(version) = caps.get(1) {
                                return Some(version.as_str().to_string());
                            }
                        }
                    }
                }

                if attempt < 2 {
                    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                }
            }

            // winget 失败，fallback 到 npmmirror
            if let Ok(response) = reqwest::get("https://cdn.npmmirror.com/binaries/node/index.json").await {
                if let Ok(json) = response.json::<Vec<serde_json::Value>>().await {
                    for entry in &json {
                        if entry.get("lts").and_then(|v| v.as_str()).is_some()
                            || entry.get("lts").and_then(|v| v.as_bool()).unwrap_or(false) == false
                        {
                            // lts field is either a string (codename) or false
                            if entry.get("lts").and_then(|v| v.as_str()).is_some() {
                                if let Some(version) = entry.get("version").and_then(|v| v.as_str()) {
                                    let ver = version.trim_start_matches('v');
                                    return Some(ver.to_string());
                                }
                            }
                        }
                    }
                }
            }

            None
        }

        #[cfg(target_os = "macos")]
        {
            // macOS: 使用 brew 检查最新版本
            if let Ok(output) = tokio::process::Command::new("brew")
                .args(&["info", "node", "--json=v2"])
                .output()
                .await
            {
                if output.status.success() {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&stdout) {
                        if let Some(version) = json["formulae"][0]["versions"]["stable"].as_str() {
                            return Some(version.to_string());
                        }
                    }
                }
            }
            None
        }

        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            None
        }
    }

    /// 从 npm registry 获取包的最新版本，npmjs 不通时兜底 npmmirror（内网/代理环境常见）
    async fn fetch_npm_latest_version(package: &str) -> Option<String> {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .ok()?;

        let urls = [
            format!("https://registry.npmjs.org/{}/latest", package),
            format!("https://registry.npmmirror.com/{}/latest", package),
        ];

        for url in &urls {
            if let Ok(response) = client.get(url).send().await {
                if response.status().is_success() {
                    if let Ok(json) = response.json::<serde_json::Value>().await {
                        if let Some(version) = json.get("version").and_then(|v| v.as_str()) {
                            return Some(version.to_string());
                        }
                    }
                }
            }
        }

        None
    }

    async fn get_claude_latest_version() -> Option<String> {
        Self::fetch_npm_latest_version("@anthropic-ai/claude-code").await
    }

    async fn get_codex_latest_version() -> Option<String> {
        Self::fetch_npm_latest_version("@openai/codex").await
    }

    async fn get_gitbash_latest_version() -> Option<String> {
        #[cfg(windows)]
        {
            // Windows: 先尝试 winget，失败则从 npmmirror 获取
            for attempt in 0..3 {
                let mut cmd = tokio::process::Command::new("winget");
                cmd.args(&["show", "Git.Git"]);
                #[cfg(windows)]
                cmd.creation_flags(CREATE_NO_WINDOW);
                if let Ok(output) = cmd.output().await
                {
                    if output.status.success() {
                        let stdout = String::from_utf8_lossy(&output.stdout);

                        if let Some(caps) = Regex::new(r"版本:\s*(\d+\.\d+\.\d+)").unwrap().captures(&stdout) {
                            if let Some(version) = caps.get(1) {
                                return Some(version.as_str().to_string());
                            }
                        }

                        if let Some(caps) = Regex::new(r"Version:\s*(\d+\.\d+\.\d+)").unwrap().captures(&stdout) {
                            if let Some(version) = caps.get(1) {
                                return Some(version.as_str().to_string());
                            }
                        }
                    }
                }

                if attempt < 2 {
                    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                }
            }

            // winget 失败，fallback 到 npmmirror git-for-windows 镜像
            if let Ok(response) = reqwest::get("https://registry.npmmirror.com/-/binary/git-for-windows/").await {
                if let Ok(json) = response.json::<Vec<serde_json::Value>>().await {
                    let re = Regex::new(r"^v([\d.]+)\.windows\.\d+/$").unwrap();
                    let mut best_version: Option<String> = None;
                    for entry in &json {
                        if let Some(name) = entry.get("name").and_then(|v| v.as_str()) {
                            if name.contains("rc") { continue; }
                            if let Some(caps) = re.captures(name) {
                                if let Some(ver) = caps.get(1) {
                                    let v = ver.as_str().to_string();
                                    if best_version.is_none() || !Self::compare_versions(best_version.as_ref().unwrap(), &v) {
                                        best_version = Some(v);
                                    }
                                }
                            }
                        }
                    }
                    if best_version.is_some() {
                        return best_version;
                    }
                }
            }

            None
        }

        #[cfg(target_os = "macos")]
        {
            // macOS: 使用 brew 检查最新版本
            if let Ok(output) = tokio::process::Command::new("brew")
                .args(&["info", "git", "--json=v2"])
                .output()
                .await
            {
                if output.status.success() {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&stdout) {
                        if let Some(version) = json["formulae"][0]["versions"]["stable"].as_str() {
                            return Some(version.to_string());
                        }
                    }
                }
            }
            None
        }

        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            None
        }
    }

    /// Check if a Git installer process (Inno Setup) is still running.
    /// Git's Inno Setup extracts git.exe before the installer finishes,
    /// so we must wait for the setup process to exit before reporting installed.
    #[cfg(windows)]
    fn is_git_installer_running() -> bool {
        // Check for processes with "Git" in their name (e.g. Git-2.47.1-64-bit.exe)
        let mut cmd = Command::new("powershell");
        cmd.args(["-NoProfile", "-Command",
            "Get-Process | Where-Object { $_.Name -match 'Git.*64.*bit' -or ($_.Name -match 'Git' -and $_.Name -match 'Setup') } | Select-Object -First 1 | ForEach-Object { $_.Id }"
        ]);
        hide_window(&mut cmd);
        if let Ok(out) = cmd.output() {
            let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !stdout.is_empty() {
                log::info!("Git installer still running (PID: {}), waiting...", stdout);
                return true;
            }
        }
        false
    }

    #[cfg(windows)]
    pub fn refresh_system_path() {
        use winreg::RegKey;
        use winreg::enums::*;
        use std::env;

        let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
        let hkcu = RegKey::predef(HKEY_CURRENT_USER);

        let system_path = hklm
            .open_subkey(r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
            .and_then(|key| key.get_value::<String, _>("Path"))
            .unwrap_or_default();

        let user_path = hkcu
            .open_subkey(r"Environment")
            .and_then(|key| key.get_value::<String, _>("Path"))
            .unwrap_or_default();

        let registry_path = if !user_path.is_empty() {
            format!("{};{}", system_path, user_path)
        } else {
            system_path
        };

        let original_path = env::var("PATH").unwrap_or_default();

        let registry_entries: Vec<&str> = registry_path.split(';').collect();
        let original_entries: Vec<&str> = original_path.split(';').collect();

        let mut new_entries: Vec<String> = Vec::new();
        for entry in &registry_entries {
            if !entry.is_empty() && !original_entries.iter().any(|e| e.eq_ignore_ascii_case(entry)) {
                new_entries.push(entry.to_string());
            }
        }

        // Also ensure npm global bin dir is in PATH
        // (npm installs claude/codex here but GUI apps may not have it)
        if let Some(home) = dirs::home_dir() {
            let npm_global = home.join(r"AppData\Roaming\npm");
            if npm_global.exists() {
                let npm_str = npm_global.to_string_lossy().to_string();
                if !new_entries.iter().any(|e| e.eq_ignore_ascii_case(&npm_str))
                    && !original_entries.iter().any(|e| e.eq_ignore_ascii_case(&npm_str))
                {
                    new_entries.push(npm_str);
                }
            }
        }

        let new_path = if new_entries.is_empty() {
            original_path
        } else {
            format!("{};{}", new_entries.join(";"), original_path)
        };

        env::set_var("PATH", new_path);
    }
}
