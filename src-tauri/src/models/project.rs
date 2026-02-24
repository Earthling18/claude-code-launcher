use serde::{Deserialize, Serialize};

fn default_skip_permissions() -> bool {
    true
}

fn default_mode() -> String {
    "claude".to_string()
}

fn default_bridge_server_url() -> String {
    "ws://172.21.11.82:80/bridge".to_string()
}

fn default_bridge_agent_port() -> u16 {
    5000
}

fn default_bridge_agent_timeout() -> u32 {
    1800
}

fn default_bridge_reconnect_interval() -> u32 {
    5
}

fn default_bridge_heartbeat_interval() -> u32 {
    30
}

fn default_bridge_agent_mode() -> String {
    "claude".to_string()
}

fn default_bridge_max_turns() -> u32 {
    3
}

/// Project-specific configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectConfig {
    #[serde(default = "default_mode")]
    pub mode: String,                    // "claude", "custom", or "remote"
    #[serde(default)]
    pub proxy: String,                   // HTTP/HTTPS proxy for Claude mode
    #[serde(default)]
    pub model: String,                   // Model name for custom mode
    #[serde(default)]
    pub base_url: String,                // API base URL for custom mode
    #[serde(default)]
    pub token: String,                   // API token (Base64 encoded in storage)
    #[serde(default = "default_skip_permissions")]
    pub skip_permissions: bool,          // Skip permissions flag

    // Remote bridge fields
    #[serde(default = "default_bridge_server_url")]
    pub bridge_server_url: String,       // Bridge server WebSocket URL
    #[serde(default)]
    pub bridge_bind_key: String,         // User bind key (sk-xxx, Base64 encoded in storage)
    #[serde(default)]
    pub bridge_client_id: String,        // Client ID (empty = use hostname)
    #[serde(default = "default_bridge_agent_port")]
    pub bridge_agent_port: u16,          // Agent server port
    #[serde(default = "default_bridge_agent_timeout")]
    pub bridge_agent_timeout: u32,       // Agent request timeout (seconds)
    #[serde(default)]
    pub bridge_proxy: String,            // HTTP proxy for bridge connections
    #[serde(default = "default_bridge_reconnect_interval")]
    pub bridge_reconnect_interval: u32,  // Reconnect interval (seconds)
    #[serde(default = "default_bridge_heartbeat_interval")]
    pub bridge_heartbeat_interval: u32,  // Heartbeat interval (seconds)
    #[serde(default = "default_bridge_agent_mode")]
    pub bridge_agent_mode: String,       // "claude" or "custom" — agent model mode for remote bridge
    #[serde(default = "default_bridge_max_turns")]
    pub bridge_max_turns: u32,           // Max turns for Claude Agent SDK (default 30)
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
            bridge_server_url: default_bridge_server_url(),
            bridge_bind_key: String::new(),
            bridge_client_id: String::new(),
            bridge_agent_port: 5000,
            bridge_agent_timeout: 1800,
            bridge_proxy: String::new(),
            bridge_reconnect_interval: 5,
            bridge_heartbeat_interval: 30,
            bridge_agent_mode: "claude".to_string(),
            bridge_max_turns: 3,
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
