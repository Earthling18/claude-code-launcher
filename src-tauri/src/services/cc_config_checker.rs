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
pub struct ConfigScanResult {
    pub conflicts: Vec<ConfigConflict>,
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
        let json: serde_json::Value = match serde_json::from_str(&content) {
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

    /// Scan all sources for conflicting config
    pub fn scan_all(projects: &[ProjectInfo]) -> ConfigScanResult {
        let mut conflicts = Vec::new();

        // 1. System environment variables
        for &key in TARGET_KEYS {
            if let Ok(val) = std::env::var(key) {
                if !val.is_empty() {
                    conflicts.push(ConfigConflict {
                        source: "env".to_string(),
                        file_path: None,
                        key: key.to_string(),
                        value: Self::mask_value(key, &val),
                        can_clean: false,
                    });
                }
            }
        }

        // 2. Global config: ~/.claude/settings.json
        if let Some(home) = dirs::home_dir() {
            let global_path = home.join(".claude").join("settings.json");
            let global_path_str = global_path.to_string_lossy().to_string();
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
            }
        }

        ConfigScanResult { conflicts }
    }

    /// Remove a single key from a settings file's "env" object
    pub fn clean_field(file_path: &str, key: &str) -> Result<(), String> {
        let content = std::fs::read_to_string(file_path)
            .map_err(|e| format!("Failed to read {}: {}", file_path, e))?;
        let mut json: serde_json::Value = serde_json::from_str(&content)
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
