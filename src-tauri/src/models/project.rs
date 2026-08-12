use serde::{Deserialize, Serialize};

fn default_skip_permissions() -> bool {
    true
}

fn default_mode() -> String {
    "claude".to_string()
}

fn default_custom_cli() -> String {
    "claude".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectConfig {
    #[serde(default = "default_mode")]
    pub mode: String,                    // "claude", "custom", or "codex"
    #[serde(default)]
    pub proxy: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub token: String,
    #[serde(default = "default_skip_permissions")]
    pub skip_permissions: bool,
    #[serde(default)]
    pub codex_api_key: String,
    #[serde(default = "default_custom_cli")]
    pub custom_cli: String,

    /// Legacy shared proxy reference. New writes use the CLI-specific fields below.
    #[serde(default)]
    pub proxy_preset_id: Option<String>,
    #[serde(default)]
    pub claude_proxy_preset_id: Option<String>,
    #[serde(default)]
    pub codex_proxy_preset_id: Option<String>,
    /// Reference to a ModelPreset (custom mode). When set, takes precedence over `model` / `base_url` / `token`.
    #[serde(default)]
    pub model_preset_id: Option<String>,
    /// CLI-specific model references. `model_preset_id` remains the legacy fallback.
    #[serde(default)]
    pub claude_model_preset_id: Option<String>,
    #[serde(default)]
    pub codex_model_preset_id: Option<String>,
}

impl ProjectConfig {
    /// Coerce legacy mode='remote' (from Mobot Launcher era) to 'claude'.
    pub fn normalize_legacy_mode(&mut self) {
        if self.mode == "remote" {
            self.mode = "claude".to_string();
        }
        if self.mode == "claude" && self.claude_proxy_preset_id.is_none() {
            self.claude_proxy_preset_id = self.proxy_preset_id.clone();
        } else if self.mode == "codex" && self.codex_proxy_preset_id.is_none() {
            self.codex_proxy_preset_id = self.proxy_preset_id.clone();
        }
        if self.mode == "custom" {
            if self.custom_cli == "codex" && self.codex_model_preset_id.is_none() {
                self.codex_model_preset_id = self.model_preset_id.clone();
            } else if self.custom_cli != "codex" && self.claude_model_preset_id.is_none() {
                self.claude_model_preset_id = self.model_preset_id.clone();
            }
        }
    }
}

impl Default for ProjectConfig {
    fn default() -> Self {
        Self {
            mode: "claude".to_string(),
            proxy: String::new(),
            model: String::new(),
            base_url: String::new(),
            token: String::new(),
            skip_permissions: true,
            codex_api_key: String::new(),
            custom_cli: "claude".to_string(),
            proxy_preset_id: None,
            claude_proxy_preset_id: None,
            codex_proxy_preset_id: None,
            model_preset_id: None,
            claude_model_preset_id: None,
            codex_model_preset_id: None,
        }
    }
}

/// A project represents a working directory with its associated configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub id: String,                      // UUID
    pub name: String,                    // Project name
    pub working_directory: String,       // Working directory path
    pub config: ProjectConfig,           // Project configuration
    pub is_default: bool,                // Whether this is the default project
    pub created_at: u64,                 // Unix timestamp
    pub updated_at: u64,                 // Unix timestamp
    #[serde(default)]
    pub last_launched_at: Option<u64>,   // Last launch timestamp
    #[serde(default)]
    pub is_pinned: bool,                 // Whether this project is pinned
    #[serde(default)]
    pub pinned_at: Option<u64>,          // Timestamp when pinned (for sorting pinned projects)
    #[serde(default)]
    pub sort_order: u32,                 // Sort order for non-pinned projects (lower = earlier)
}

impl Project {
    pub fn new(name: String, working_directory: String, config: ProjectConfig, is_default: bool) -> Self {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        Self {
            id: uuid_v4(),
            name,
            working_directory,
            config,
            is_default,
            created_at: now,
            updated_at: now,
            last_launched_at: None,
            is_pinned: false,
            pinned_at: None,
            sort_order: 0,
        }
    }

    pub fn new_with_sort_order(name: String, working_directory: String, config: ProjectConfig, is_default: bool, sort_order: u32) -> Self {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        Self {
            id: uuid_v4(),
            name,
            working_directory,
            config,
            is_default,
            created_at: now,
            updated_at: now,
            last_launched_at: None,
            is_pinned: false,
            pinned_at: None,
            sort_order,
        }
    }

    pub fn default_project() -> Self {
        let home_dir = dirs::home_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "~".to_string());

        Self::new(
            "默认项目".to_string(),
            home_dir,
            ProjectConfig::default(),
            true,
        )
    }
}

/// Input for creating a new project
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CreateProjectInput {
    pub name: String,
    pub working_directory: String,
    pub config: ProjectConfig,
}

/// Input for updating an existing project
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateProjectInput {
    pub name: Option<String>,
    pub working_directory: Option<String>,
    pub config: Option<ProjectConfig>,
    pub is_pinned: Option<bool>,
}

/// Input for updating project order (batch)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectOrderItem {
    pub id: String,
    pub sort_order: u32,
}

/// Input for updating pinned project order (batch)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PinnedOrderItem {
    pub id: String,
    pub pinned_at: u64,
}

/// Generate a simple UUID v4
fn uuid_v4() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();

    // Simple pseudo-random generation based on timestamp and a counter
    let random_part = timestamp ^ (timestamp >> 32);

    format!(
        "{:08x}-{:04x}-4{:03x}-{:04x}-{:012x}",
        (random_part & 0xFFFFFFFF) as u32,
        ((random_part >> 32) & 0xFFFF) as u16,
        ((random_part >> 48) & 0x0FFF) as u16,
        (0x8000 | ((random_part >> 60) & 0x3FFF)) as u16,
        (random_part & 0xFFFFFFFFFFFF) as u64
    )
}

#[cfg(test)]
mod proxy_config_tests {
    use super::ProjectConfig;

    #[test]
    fn legacy_shared_proxy_moves_only_to_current_cli() {
        let mut claude: ProjectConfig = serde_json::from_str(
            r#"{"mode":"claude","proxy_preset_id":"proxy-a"}"#,
        )
        .unwrap();
        claude.normalize_legacy_mode();
        assert_eq!(claude.claude_proxy_preset_id.as_deref(), Some("proxy-a"));
        assert_eq!(claude.codex_proxy_preset_id, None);

        let mut codex: ProjectConfig =
            serde_json::from_str(r#"{"mode":"codex","proxy_preset_id":"proxy-b"}"#).unwrap();
        codex.normalize_legacy_mode();
        assert_eq!(codex.claude_proxy_preset_id, None);
        assert_eq!(codex.codex_proxy_preset_id.as_deref(), Some("proxy-b"));
    }

    #[test]
    fn cli_specific_proxy_selections_survive_together() {
        let config = ProjectConfig {
            claude_proxy_preset_id: Some("claude-proxy".to_string()),
            codex_proxy_preset_id: Some("codex-proxy".to_string()),
            ..ProjectConfig::default()
        };
        let json = serde_json::to_string(&config).unwrap();
        let restored: ProjectConfig = serde_json::from_str(&json).unwrap();

        assert_eq!(
            restored.claude_proxy_preset_id.as_deref(),
            Some("claude-proxy")
        );
        assert_eq!(
            restored.codex_proxy_preset_id.as_deref(),
            Some("codex-proxy")
        );
    }

    #[test]
    fn legacy_custom_model_moves_only_to_the_selected_cli() {
        let mut codex: ProjectConfig = serde_json::from_str(
            r#"{"mode":"custom","custom_cli":"codex","model_preset_id":"legacy-model"}"#,
        )
        .unwrap();
        codex.normalize_legacy_mode();
        assert_eq!(codex.codex_model_preset_id.as_deref(), Some("legacy-model"));
        assert_eq!(codex.claude_model_preset_id, None);

        let mut claude: ProjectConfig = serde_json::from_str(
            r#"{"mode":"custom","custom_cli":"claude","model_preset_id":"legacy-model"}"#,
        )
        .unwrap();
        claude.normalize_legacy_mode();
        assert_eq!(
            claude.claude_model_preset_id.as_deref(),
            Some("legacy-model")
        );
        assert_eq!(claude.codex_model_preset_id, None);
    }
}
