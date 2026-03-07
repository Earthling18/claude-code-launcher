use serde::{Deserialize, Serialize};
use std::path::Path;

/// Fields we check for conflicts
const TARGET_KEYS: &[&str] = &[
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigConflict {
    pub source: String,
    pub file_path: Option<String>,
    pub key: String,
    pub value: String,
    pub can_clean: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BomFileIssue {
    pub file_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpMisplaced {
    pub file_path: String,
    pub target_path: String,
    pub keys: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigScanResult {
    pub conflicts: Vec<ConfigConflict>,
    pub bom_files: Vec<BomFileIssue>,
    pub mcp_misplaced: Vec<McpMisplaced>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CleanTarget {
    pub file_path: String,
    pub key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectInfo {
    pub name: String,
    pub working_directory: String,
}

pub struct CcConfigChecker;

impl CcConfigChecker {
    /// Mask sensitive values: show first 6 chars + "..." + last 4 chars
    fn mask_value(key: &str, value: &str) -> String {
        let is_sensitive = key.contains("KEY") || key.contains("TOKEN");
        if !is_sensitive || value.len() <= 12 {
            return value.to_string();
        }
        let prefix = &value[..6.min(value.len())];
        let suffix = &value[value.len().saturating_sub(4)..];
        format!("{}...{}", prefix, suffix)
    }

    /// Read a JSON file and extract target keys from the "env" object
    fn scan_settings_file(file_path: &str) -> Vec<(String, String)> {
        let content = match std::fs::read_to_string(file_path) {
            Ok(c) => c,
            Err(_) => return vec![],
        };
        // Strip BOM before parsing
        let content = content.strip_prefix('\u{feff}').unwrap_or(&content);
        let json: serde_json::Value = match serde_json::from_str(content) {
            Ok(v) => v,
            Err(_) => return vec![],
        };
        let env_obj = match json.get("env").and_then(|v| v.as_object()) {
            Some(obj) => obj,
            None => return vec![],
        };
        let mut results = vec![];
        for &key in TARGET_KEYS {
            if let Some(val) = env_obj.get(key).and_then(|v| v.as_str()) {
                if !val.is_empty() {
                    results.push((key.to_string(), val.to_string()));
                }
            }
        }
        results
    }

    /// Scan shell profile files (macOS/Linux) for persistent export statements
    #[cfg(not(windows))]
    fn scan_shell_profiles() -> Vec<ConfigConflict> {
        let mut conflicts = Vec::new();
        let home = match dirs::home_dir() {
            Some(h) => h,
            None => return conflicts,
        };
        let profiles = [".zshrc", ".bashrc", ".bash_profile", ".zprofile"];
        for profile_name in &profiles {
            let profile_path = home.join(profile_name);
            let content = match std::fs::read_to_string(&profile_path) {
                Ok(c) => c,
                Err(_) => continue,
            };
            let profile_path_str = profile_path.to_string_lossy().to_string();
            for line in content.lines() {
                let trimmed = line.trim();
                // Skip comments
                if trimmed.starts_with('#') {
                    continue;
                }
                for &key in TARGET_KEYS {
                    // Match: export KEY=value or export KEY="value" or KEY=value
                    let patterns = [
                        format!("export {}=", key),
                        format!("{}=", key),
                    ];
                    for pat in &patterns {
                        if trimmed.starts_with(pat.as_str()) {
                            let raw_val = trimmed[pat.len()..].trim();
                            // Strip quotes
                            let val = raw_val
                                .trim_matches('"')
                                .trim_matches('\'')
                                .to_string();
                            if !val.is_empty() {
                                conflicts.push(ConfigConflict {
                                    source: "shell_profile".to_string(),
                                    file_path: Some(profile_path_str.clone()),
                                    key: key.to_string(),
                                    value: Self::mask_value(key, &val),
                                    can_clean: false,
                                });
                            }
                            break;
                        }
                    }
                }
            }
        }
        // Deduplicate: keep only the last occurrence per key (later profiles override earlier ones)
        let mut seen = std::collections::HashSet::new();
        conflicts.reverse();
        conflicts.retain(|c| seen.insert((c.key.clone(), c.file_path.clone())));
        conflicts.reverse();
        conflicts
    }

    /// Scan Windows registry for persistent environment variables
    #[cfg(windows)]
    fn scan_shell_profiles() -> Vec<ConfigConflict> {
        let mut conflicts = Vec::new();

        // Read from HKCU\Environment (user-level persistent env vars)
        if let Ok(hkcu) = winreg::RegKey::predef(winreg::enums::HKEY_CURRENT_USER)
            .open_subkey("Environment")
        {
            for &key in TARGET_KEYS {
                if let Ok(val) = hkcu.get_value::<String, _>(key) {
                    if !val.is_empty() {
                        conflicts.push(ConfigConflict {
                            source: "registry_user".to_string(),
                            file_path: None,
                            key: key.to_string(),
                            value: Self::mask_value(key, &val),
                            can_clean: false,
                        });
                    }
                }
            }
        }

        // Read from HKLM\SYSTEM\...\Environment (system-level persistent env vars)
        if let Ok(hklm) = winreg::RegKey::predef(winreg::enums::HKEY_LOCAL_MACHINE)
            .open_subkey(r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
        {
            for &key in TARGET_KEYS {
                if let Ok(val) = hklm.get_value::<String, _>(key) {
                    if !val.is_empty() {
                        conflicts.push(ConfigConflict {
                            source: "registry_system".to_string(),
                            file_path: None,
                            key: key.to_string(),
                            value: Self::mask_value(key, &val),
                            can_clean: false,
                        });
                    }
                }
            }
        }

        conflicts
    }

    /// Check if a file starts with UTF-8 BOM
    fn check_bom(file_path: &str) -> bool {
        match std::fs::read(file_path) {
            Ok(bytes) => bytes.starts_with(&[0xEF, 0xBB, 0xBF]),
            Err(_) => false,
        }
    }

    /// Check if a settings.json file contains mcpServers key (misplaced MCP config)
    fn check_mcp_misplaced(file_path: &str) -> Option<Vec<String>> {
        let content = std::fs::read_to_string(file_path).ok()?;
        let content = content.strip_prefix('\u{feff}').unwrap_or(&content);
        let json: serde_json::Value = serde_json::from_str(content).ok()?;
        if let Some(mcp) = json.get("mcpServers").and_then(|v| v.as_object()) {
            if !mcp.is_empty() {
                return Some(mcp.keys().cloned().collect());
            }
        }
        None
    }

    /// Scan all sources for conflicting config
    pub fn scan_all(projects: &[ProjectInfo]) -> ConfigScanResult {
        let mut conflicts = Vec::new();
        let mut bom_files = Vec::new();
        let mut mcp_misplaced = Vec::new();

        // 1. Persistent system environment variables (shell profiles / registry)
        conflicts.extend(Self::scan_shell_profiles());

        // 2. Global config: ~/.claude/settings.json
        if let Some(home) = dirs::home_dir() {
            let claude_dir = home.join(".claude");
            let global_path = claude_dir.join("settings.json");
            let global_path_str = global_path.to_string_lossy().to_string();

            if global_path.exists() {
                let found = Self::scan_settings_file(&global_path_str);
                for (key, val) in found {
                    conflicts.push(ConfigConflict {
                        source: "global".to_string(),
                        file_path: Some(global_path_str.clone()),
                        key: key.clone(),
                        value: Self::mask_value(&key, &val),
                        can_clean: true,
                    });
                }

                // BOM check
                if Self::check_bom(&global_path_str) {
                    bom_files.push(BomFileIssue { file_path: global_path_str.clone() });
                }

                // MCP misplaced check
                if let Some(keys) = Self::check_mcp_misplaced(&global_path_str) {
                    let target = claude_dir.join(".mcp.json").to_string_lossy().to_string();
                    mcp_misplaced.push(McpMisplaced {
                        file_path: global_path_str.clone(),
                        target_path: target,
                        keys,
                    });
                }
            }

            // Also check global settings.local.json for BOM
            let global_local = claude_dir.join("settings.local.json");
            if global_local.exists() {
                let path_str = global_local.to_string_lossy().to_string();
                if Self::check_bom(&path_str) {
                    bom_files.push(BomFileIssue { file_path: path_str });
                }
            }
        }

        // 3. Project-level configs
        for project in projects {
            let base = Path::new(&project.working_directory).join(".claude");
            for filename in &["settings.json", "settings.local.json"] {
                let file_path = base.join(filename);
                if !file_path.exists() {
                    continue;
                }
                let file_path_str = file_path.to_string_lossy().to_string();

                // Config conflicts
                let found = Self::scan_settings_file(&file_path_str);
                for (key, val) in found {
                    conflicts.push(ConfigConflict {
                        source: format!("project:{}", project.name),
                        file_path: Some(file_path_str.clone()),
                        key: key.clone(),
                        value: Self::mask_value(&key, &val),
                        can_clean: true,
                    });
                }

                // BOM check
                if Self::check_bom(&file_path_str) {
                    bom_files.push(BomFileIssue { file_path: file_path_str.clone() });
                }

                // MCP misplaced check (only for settings.json, not settings.local.json)
                if *filename == "settings.json" {
                    if let Some(keys) = Self::check_mcp_misplaced(&file_path_str) {
                        // Project-level .mcp.json goes in project root, not .claude/
                        let target = Path::new(&project.working_directory).join(".mcp.json").to_string_lossy().to_string();
                        mcp_misplaced.push(McpMisplaced {
                            file_path: file_path_str.clone(),
                            target_path: target,
                            keys,
                        });
                    }
                }
            }

            // Also check project root .mcp.json for BOM
            let mcp_json = Path::new(&project.working_directory).join(".mcp.json");
            if mcp_json.exists() {
                let mcp_path_str = mcp_json.to_string_lossy().to_string();
                if Self::check_bom(&mcp_path_str) {
                    bom_files.push(BomFileIssue { file_path: mcp_path_str });
                }
            }
        }

        ConfigScanResult { conflicts, bom_files, mcp_misplaced }
    }

    /// Remove a single key from a settings file's "env" object
    pub fn clean_field(file_path: &str, key: &str) -> Result<(), String> {
        let content = std::fs::read_to_string(file_path)
            .map_err(|e| format!("Failed to read {}: {}", file_path, e))?;
        let content = content.strip_prefix('\u{feff}').unwrap_or(&content);
        let mut json: serde_json::Value = serde_json::from_str(content)
            .map_err(|e| format!("Failed to parse {}: {}", file_path, e))?;

        if let Some(env_obj) = json.get_mut("env").and_then(|v| v.as_object_mut()) {
            env_obj.remove(key);
        }

        let output = serde_json::to_string_pretty(&json)
            .map_err(|e| format!("Failed to serialize JSON: {}", e))?;
        std::fs::write(file_path, output)
            .map_err(|e| format!("Failed to write {}: {}", file_path, e))?;

        Ok(())
    }

    /// Batch clean multiple targets, returns count of cleaned fields
    pub fn clean_all(targets: &[CleanTarget]) -> Result<u32, String> {
        let mut count = 0u32;
        for target in targets {
            Self::clean_field(&target.file_path, &target.key)?;
            count += 1;
        }
        Ok(count)
    }

    /// Remove UTF-8 BOM from a file
    pub fn fix_bom(file_path: &str) -> Result<(), String> {
        let bytes = std::fs::read(file_path)
            .map_err(|e| format!("Failed to read {}: {}", file_path, e))?;
        if bytes.starts_with(&[0xEF, 0xBB, 0xBF]) {
            std::fs::write(file_path, &bytes[3..])
                .map_err(|e| format!("Failed to write {}: {}", file_path, e))?;
        }
        Ok(())
    }

    /// Move mcpServers from settings.json to .mcp.json
    pub fn fix_mcp_misplaced(file_path: &str, target_path: &str) -> Result<(), String> {
        // Read source
        let content = std::fs::read_to_string(file_path)
            .map_err(|e| format!("Failed to read {}: {}", file_path, e))?;
        let content_clean = content.strip_prefix('\u{feff}').unwrap_or(&content);
        let mut source_json: serde_json::Value = serde_json::from_str(content_clean)
            .map_err(|e| format!("Failed to parse {}: {}", file_path, e))?;

        // Extract mcpServers
        let mcp_servers = match source_json.get("mcpServers").cloned() {
            Some(v) => v,
            None => return Ok(()), // Nothing to move
        };

        // Read or create target .mcp.json
        let mut target_json: serde_json::Value = if Path::new(target_path).exists() {
            let target_content = std::fs::read_to_string(target_path)
                .map_err(|e| format!("Failed to read {}: {}", target_path, e))?;
            let target_clean = target_content.strip_prefix('\u{feff}').unwrap_or(&target_content);
            serde_json::from_str(target_clean)
                .map_err(|e| format!("Failed to parse {}: {}", target_path, e))?
        } else {
            serde_json::json!({})
        };

        // Merge mcpServers into target (existing entries preserved, new ones added)
        if let Some(servers) = mcp_servers.as_object() {
            let target_servers = target_json
                .as_object_mut()
                .ok_or("Target .mcp.json is not an object")?
                .entry("mcpServers")
                .or_insert(serde_json::json!({}));
            if let Some(target_map) = target_servers.as_object_mut() {
                for (k, v) in servers {
                    if !target_map.contains_key(k) {
                        target_map.insert(k.clone(), v.clone());
                    }
                }
            }
        }

        // Write target
        let target_output = serde_json::to_string_pretty(&target_json)
            .map_err(|e| format!("Failed to serialize JSON: {}", e))?;
        std::fs::write(target_path, target_output)
            .map_err(|e| format!("Failed to write {}: {}", target_path, e))?;

        // Remove mcpServers from source
        if let Some(obj) = source_json.as_object_mut() {
            obj.remove("mcpServers");
        }
        let source_output = serde_json::to_string_pretty(&source_json)
            .map_err(|e| format!("Failed to serialize JSON: {}", e))?;
        std::fs::write(file_path, source_output)
            .map_err(|e| format!("Failed to write {}: {}", file_path, e))?;

        Ok(())
    }

    /// Open a file with the system default editor
    pub fn open_file(file_path: &str) -> Result<(), String> {
        #[cfg(target_os = "macos")]
        {
            std::process::Command::new("open")
                .arg(file_path)
                .spawn()
                .map_err(|e| format!("Failed to open file: {}", e))?;
        }
        #[cfg(target_os = "windows")]
        {
            std::process::Command::new("cmd")
                .args(["/C", "start", "", file_path])
                .spawn()
                .map_err(|e| format!("Failed to open file: {}", e))?;
        }
        #[cfg(target_os = "linux")]
        {
            std::process::Command::new("xdg-open")
                .arg(file_path)
                .spawn()
                .map_err(|e| format!("Failed to open file: {}", e))?;
        }
        Ok(())
    }
}
