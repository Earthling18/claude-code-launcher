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
}

impl ProjectConfig {
    /// Coerce legacy mode='remote' (from Mobot Launcher era) to 'claude'.
    pub fn normalize_legacy_mode(&mut self) {
        if self.mode == "remote" {
            self.mode = "claude".to_string();
        }
    }
}

impl Default for ProjectConfig {
    fn default() -> Self {
        Self {
            mode: "claude".to_string(),
            proxy: String::new(),
            model: "qwen3-coder-480b-a35b".to_string(),
            base_url: "http://litellm.uattest.weoa.com".to_string(),
            token: String::new(),
            skip_permissions: true,
            codex_api_key: String::new(),
            custom_cli: "claude".to_string(),
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
