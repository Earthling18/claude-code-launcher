use serde::{Deserialize, Serialize};
use std::process::Command;
use regex::Regex;

#[cfg(target_os = "macos")]
use std::env;

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

        #[cfg(not(target_os = "macos"))]
        Self::check_dependency("node", &["--version"], r"v(\d+\.\d+\.\d+)", Some("18.0.0"))
    }

    pub fn check_gitbash() -> DependencyStatus {
        Self::check_dependency("git", &["--version"], r"git version (\d+\.\d+\.\d+)", None)
    }

    pub fn check_claude() -> DependencyStatus {
        #[cfg(windows)]
        Self::refresh_system_path();

        // 跨平台检测 claude
        #[cfg(windows)]
        let output = Command::new("cmd")
            .args(&["/c", "claude", "--version"])
            .output();

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
                // claude --version failed. Check if the npm package is installed
                // but the symlink/shim is missing, and auto-repair if so.
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    const CREATE_NO_WINDOW: u32 = 0x08000000;

                    // Check if npm itself is available
                    let npm_available = Command::new("cmd")
                        .args(&["/c", "where", "npm"])
                        .creation_flags(CREATE_NO_WINDOW)
                        .output()
                        .map(|o| o.status.success())
                        .unwrap_or(false);

                    if npm_available {
                        // claude not found but npm is available — reinstall to repair
                        eprintln!("[check_claude] Windows: claude not found, attempting reinstall...");
                        let _ = Command::new("cmd")
                            .args(&["/c", "npm", "install", "-g", "@anthropic-ai/claude-code"])
                            .creation_flags(CREATE_NO_WINDOW)
                            .output();

                        Self::refresh_system_path();

                        // Retry version check after repair
                        let retry = Command::new("cmd")
                            .args(&["/c", "claude", "--version"])
                            .creation_flags(CREATE_NO_WINDOW)
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

                #[cfg(target_os = "macos")]
                {
                    // On macOS, if claude command is missing, attempt auto-repair.
                    // This handles both cases:
                    // 1. npm package exists but symlink is broken
                    // 2. npm package was corrupted/removed by a failed auto-update
                    // In both cases, npm install -g will fix it.
                    let extended_path = get_macos_extended_path();

                    // Check if npm itself is available
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

                        // Retry version check after repair
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
        let output = Command::new("cmd")
            .args(&["/c", "codex", "--version"])
            .output();

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
                // codex --version failed. Attempt auto-repair if npm is available.
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    const CREATE_NO_WINDOW: u32 = 0x08000000;

                    let npm_available = Command::new("cmd")
                        .args(&["/c", "where", "npm"])
                        .creation_flags(CREATE_NO_WINDOW)
                        .output()
                        .map(|o| o.status.success())
                        .unwrap_or(false);

                    if npm_available {
                        eprintln!("[check_codex] Windows: codex not found, attempting reinstall...");
                        let _ = Command::new("cmd")
                            .args(&["/c", "npm", "install", "-g", "@openai/codex"])
                            .creation_flags(CREATE_NO_WINDOW)
                            .output();

                        Self::refresh_system_path();

                        let retry = Command::new("cmd")
                            .args(&["/c", "codex", "--version"])
                            .creation_flags(CREATE_NO_WINDOW)
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
        let output = Command::new(command)
            .args(args)
            .output();

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
            status.latest_version = Self::get_gitbash_latest_version().await;
            if let (Some(ref current), Some(ref latest)) = (&status.version, &status.latest_version) {
                status.update_available = !Self::compare_versions(current, latest);
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
            // Windows: 使用 winget 检查最新版本
            for attempt in 0..3 {
                if let Ok(output) = tokio::process::Command::new("winget")
                    .args(&["show", "OpenJS.NodeJS.LTS"])
                    .output()
                    .await
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

    async fn get_claude_latest_version() -> Option<String> {
        // 从 npm registry 获取最新版本 (跨平台)
        let url = "https://registry.npmjs.org/@anthropic-ai/claude-code/latest";

        match reqwest::get(url).await {
            Ok(response) => {
                if let Ok(json) = response.json::<serde_json::Value>().await {
                    return json.get("version")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                }
            }
            Err(_) => {}
        }

        None
    }

    async fn get_codex_latest_version() -> Option<String> {
        let url = "https://registry.npmjs.org/@openai/codex/latest";
        match reqwest::get(url).await {
            Ok(response) => {
                if let Ok(json) = response.json::<serde_json::Value>().await {
                    return json.get("version")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());
                }
            }
            Err(_) => {}
        }
        None
    }

    async fn get_gitbash_latest_version() -> Option<String> {
        #[cfg(windows)]
        {
            // Windows: 使用 winget 检查最新版本
            for attempt in 0..3 {
                if let Ok(output) = tokio::process::Command::new("winget")
                    .args(&["show", "Git.Git"])
                    .output()
                    .await
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

        let mut new_entries = Vec::new();
        for entry in registry_entries {
            if !entry.is_empty() && !original_entries.contains(&entry) {
                new_entries.push(entry);
            }
        }

        let new_path = if new_entries.is_empty() {
            original_path
        } else {
            format!("{};{}", new_entries.join(";"), original_path)
        };

        env::set_var("PATH", new_path);

        let current_path = env::var("PATH").unwrap_or_default();
        let path_preview = if current_path.len() > 200 {
            format!("{}...", &current_path[..200])
        } else {
            current_path.clone()
        };
        eprintln!("[DEBUG] 当前 PATH (前200字符): {}", path_preview);

        let nodejs_paths = vec![
            r"C:\Program Files\nodejs",
            r"C:\Program Files (x86)\nodejs",
        ];

        for path in nodejs_paths {
            if std::path::Path::new(path).exists() {
                println!("检测到Node.js路径: {}", path);
            }
        }
    }
}
