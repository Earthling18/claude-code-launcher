use serde::{Deserialize, Serialize};

use crate::models::ProjectConfig;

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
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub token: String,
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
