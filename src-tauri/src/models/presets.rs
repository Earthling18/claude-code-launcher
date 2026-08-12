use serde::{Deserialize, Serialize};

use crate::models::ProjectConfig;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModelApiFormat {
    AnthropicMessages,
    OpenaiResponses,
}

impl Default for ModelApiFormat {
    fn default() -> Self {
        Self::AnthropicMessages
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxyPreset {
    pub id: String,
    pub name: String,
    pub url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelPreset {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub model: String,
    /// Shared model presets can expose either or both CLI-specific endpoints.
    #[serde(default)]
    pub claude_base_url: String,
    #[serde(default)]
    pub codex_base_url: String,
    /// Legacy single-endpoint fields kept for a lossless pre-v1.2.8 migration.
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub token: String,
    /// Missing on presets created before v1.2.7. Kept optional until the
    /// one-shot project-aware migration assigns the correct protocol.
    #[serde(default)]
    pub api_format: Option<ModelApiFormat>,
}

impl ModelPreset {
    pub fn endpoint(&self, format: ModelApiFormat) -> &str {
        let current = match format {
            ModelApiFormat::AnthropicMessages => &self.claude_base_url,
            ModelApiFormat::OpenaiResponses => &self.codex_base_url,
        };
        if !current.is_empty() {
            return current;
        }
        if self.api_format.unwrap_or_default() == format {
            &self.base_url
        } else {
            ""
        }
    }

    pub fn supports(&self, format: ModelApiFormat) -> bool {
        !self.endpoint(format).trim().is_empty()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GlobalPresets {
    #[serde(default)]
    pub proxies: Vec<ProxyPreset>,
    #[serde(default)]
    pub models: Vec<ModelPreset>,
    #[serde(default)]
    pub last_used_config: Option<ProjectConfig>,
}

pub fn new_preset_id() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
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
