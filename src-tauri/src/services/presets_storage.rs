use base64::{engine::general_purpose, Engine as _};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

use crate::models::{
    new_preset_id, GlobalPresets, ModelApiFormat, ModelPreset, Project, ProjectConfig, ProxyPreset,
};

/// On-disk wrapper that mirrors GlobalPresets but with token base64-encoded.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct StoredPresets {
    #[serde(default)]
    proxies: Vec<ProxyPreset>,
    #[serde(default)]
    models: Vec<ModelPreset>,
    #[serde(default)]
    last_used_config: Option<ProjectConfig>,
}

pub struct PresetsStorage;

impl PresetsStorage {
    fn get_presets_path() -> Result<PathBuf, String> {
        let base = dirs::config_dir().ok_or("无法获取配置目录")?;
        let dir = base.join("CCLauncher");
        if !dir.exists() {
            fs::create_dir_all(&dir).map_err(|e| format!("无法创建配置目录: {}", e))?;
        }
        Ok(dir.join("presets.json"))
    }

    fn encode_model(m: &mut ModelPreset) {
        if !m.token.is_empty() {
            m.token = general_purpose::STANDARD.encode(&m.token);
        }
    }

    fn decode_model(m: &mut ModelPreset) {
        if !m.token.is_empty() {
            if let Ok(decoded) = general_purpose::STANDARD.decode(&m.token) {
                if let Ok(s) = String::from_utf8(decoded) {
                    m.token = s;
                }
            }
        }
    }

    fn encode_last_used(cfg: &mut ProjectConfig) {
        if !cfg.token.is_empty() {
            cfg.token = general_purpose::STANDARD.encode(&cfg.token);
        }
        if !cfg.codex_api_key.is_empty() {
            cfg.codex_api_key = general_purpose::STANDARD.encode(&cfg.codex_api_key);
        }
    }

    fn decode_last_used(cfg: &mut ProjectConfig) {
        if !cfg.token.is_empty() {
            if let Ok(decoded) = general_purpose::STANDARD.decode(&cfg.token) {
                if let Ok(s) = String::from_utf8(decoded) {
                    cfg.token = s;
                }
            }
        }
        if !cfg.codex_api_key.is_empty() {
            if let Ok(decoded) = general_purpose::STANDARD.decode(&cfg.codex_api_key) {
                if let Ok(s) = String::from_utf8(decoded) {
                    cfg.codex_api_key = s;
                }
            }
        }
    }

    pub fn load() -> GlobalPresets {
        let path = match Self::get_presets_path() {
            Ok(p) => p,
            Err(e) => {
                log::warn!("Cannot resolve presets.json path: {}", e);
                return GlobalPresets::default();
            }
        };
        if !path.exists() {
            return GlobalPresets::default();
        }
        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(e) => {
                log::warn!("Cannot read presets.json: {}", e);
                return GlobalPresets::default();
            }
        };
        let mut stored: StoredPresets = match serde_json::from_str(&content) {
            Ok(v) => v,
            Err(e) => {
                log::warn!("Cannot parse presets.json: {}", e);
                return GlobalPresets::default();
            }
        };
        for m in &mut stored.models {
            Self::decode_model(m);
        }
        if let Some(cfg) = &mut stored.last_used_config {
            Self::decode_last_used(cfg);
        }
        GlobalPresets {
            proxies: stored.proxies,
            models: stored.models,
            last_used_config: stored.last_used_config,
        }
    }

    pub fn save(presets: &GlobalPresets) -> Result<(), String> {
        let path = Self::get_presets_path()?;
        let mut stored = StoredPresets {
            proxies: presets.proxies.clone(),
            models: presets.models.clone(),
            last_used_config: presets.last_used_config.clone(),
        };
        for m in &mut stored.models {
            Self::encode_model(m);
        }
        if let Some(cfg) = &mut stored.last_used_config {
            Self::encode_last_used(cfg);
        }
        let json =
            serde_json::to_string_pretty(&stored).map_err(|e| format!("无法序列化预设: {}", e))?;
        fs::write(&path, json).map_err(|e| format!("无法写入预设文件: {}", e))?;
        Ok(())
    }

    pub fn presets_file_exists() -> bool {
        Self::get_presets_path()
            .map(|p| p.exists())
            .unwrap_or(false)
    }

    // ------------- CRUD: ProxyPreset -------------

    pub fn create_proxy(name: String, url: String) -> Result<ProxyPreset, String> {
        let mut presets = Self::load();
        let preset = ProxyPreset {
            id: new_preset_id(),
            name: ensure_unique_name(&name, presets.proxies.iter().map(|p| p.name.as_str())),
            url,
        };
        presets.proxies.push(preset.clone());
        Self::save(&presets)?;
        Ok(preset)
    }

    pub fn update_proxy(id: &str, name: String, url: String) -> Result<ProxyPreset, String> {
        let mut presets = Self::load();
        let names: Vec<String> = presets
            .proxies
            .iter()
            .filter(|p| p.id != id)
            .map(|p| p.name.clone())
            .collect();
        let target = presets
            .proxies
            .iter_mut()
            .find(|p| p.id == id)
            .ok_or_else(|| format!("代理预设不存在: {}", id))?;
        target.name = ensure_unique_name(&name, names.iter().map(|s| s.as_str()));
        target.url = url;
        let updated = target.clone();
        Self::save(&presets)?;
        Ok(updated)
    }

    /// Delete proxy preset and clear references on all projects.
    pub fn delete_proxy(id: &str) -> Result<(), String> {
        let mut presets = Self::load();
        let before = presets.proxies.len();
        presets.proxies.retain(|p| p.id != id);
        if presets.proxies.len() == before {
            return Err(format!("代理预设不存在: {}", id));
        }
        Self::save(&presets)?;
        clear_proxy_ref_from_projects(id)?;
        Ok(())
    }

    // ------------- CRUD: ModelPreset -------------

    pub fn create_model(
        name: String,
        model: String,
        claude_base_url: String,
        codex_base_url: String,
        token: String,
    ) -> Result<ModelPreset, String> {
        let mut presets = Self::load();
        let preset = ModelPreset {
            id: new_preset_id(),
            name: ensure_unique_name(&name, presets.models.iter().map(|p| p.name.as_str())),
            model,
            claude_base_url,
            codex_base_url,
            base_url: String::new(),
            token,
            api_format: None,
        };
        presets.models.push(preset.clone());
        Self::save(&presets)?;
        Ok(preset)
    }

    pub fn update_model(
        id: &str,
        name: String,
        model: String,
        claude_base_url: String,
        codex_base_url: String,
        token: String,
    ) -> Result<ModelPreset, String> {
        let mut presets = Self::load();
        let names: Vec<String> = presets
            .models
            .iter()
            .filter(|p| p.id != id)
            .map(|p| p.name.clone())
            .collect();
        let target = presets
            .models
            .iter_mut()
            .find(|p| p.id == id)
            .ok_or_else(|| format!("模型预设不存在: {}", id))?;
        target.name = ensure_unique_name(&name, names.iter().map(|s| s.as_str()));
        target.model = model;
        target.claude_base_url = claude_base_url;
        target.codex_base_url = codex_base_url;
        target.base_url.clear();
        target.token = token;
        target.api_format = None;
        let updated = target.clone();
        Self::save(&presets)?;
        Ok(updated)
    }

    pub fn delete_model(id: &str) -> Result<(), String> {
        let mut presets = Self::load();
        let before = presets.models.len();
        presets.models.retain(|p| p.id != id);
        if presets.models.len() == before {
            return Err(format!("模型预设不存在: {}", id));
        }
        Self::save(&presets)?;
        clear_model_ref_from_projects(id)?;
        Ok(())
    }

    // ------------- last_used_config -------------

    pub fn get_last_used() -> Option<ProjectConfig> {
        Self::load().last_used_config
    }

    pub fn set_last_used(config: ProjectConfig) -> Result<(), String> {
        let mut presets = Self::load();
        presets.last_used_config = Some(config);
        Self::save(&presets)
    }

    /// Count how many projects reference a given proxy preset id.
    pub fn count_proxy_refs(id: &str) -> usize {
        crate::services::ConfigStorage::get_projects()
            .map(|projects| {
                projects
                    .iter()
                    .filter(|p| {
                        p.config.claude_proxy_preset_id.as_deref() == Some(id)
                            || p.config.codex_proxy_preset_id.as_deref() == Some(id)
                            || p.config.proxy_preset_id.as_deref() == Some(id)
                    })
                    .count()
            })
            .unwrap_or(0)
    }

    pub fn count_model_refs(id: &str) -> usize {
        crate::services::ConfigStorage::get_projects()
            .map(|projects| {
                projects
                    .iter()
                    .filter(|p| {
                        p.config.model_preset_id.as_deref() == Some(id)
                            || p.config.claude_model_preset_id.as_deref() == Some(id)
                            || p.config.codex_model_preset_id.as_deref() == Some(id)
                    })
                    .count()
            })
            .unwrap_or(0)
    }
}

fn ensure_unique_name<'a, I: Iterator<Item = &'a str>>(name: &str, existing: I) -> String {
    let names: std::collections::HashSet<&str> = existing.collect();
    if !names.contains(name) {
        return name.to_string();
    }
    let mut n = 2;
    loop {
        let candidate = format!("{} ({})", name, n);
        if !names.contains(candidate.as_str()) {
            return candidate;
        }
        n += 1;
    }
}

fn clear_proxy_ref_from_projects(id: &str) -> Result<(), String> {
    use crate::models::UpdateProjectInput;
    use crate::services::ConfigStorage;
    let projects = ConfigStorage::get_projects()?;
    for p in projects {
        if p.config.claude_proxy_preset_id.as_deref() == Some(id)
            || p.config.codex_proxy_preset_id.as_deref() == Some(id)
            || p.config.proxy_preset_id.as_deref() == Some(id)
        {
            let mut new_cfg = p.config.clone();
            if new_cfg.claude_proxy_preset_id.as_deref() == Some(id) {
                new_cfg.claude_proxy_preset_id = None;
            }
            if new_cfg.codex_proxy_preset_id.as_deref() == Some(id) {
                new_cfg.codex_proxy_preset_id = None;
            }
            if new_cfg.proxy_preset_id.as_deref() == Some(id) {
                new_cfg.proxy_preset_id = None;
            }
            let _ = ConfigStorage::update_project(
                &p.id,
                UpdateProjectInput {
                    name: None,
                    working_directory: None,
                    config: Some(new_cfg),
                    is_pinned: None,
                },
            );
        }
    }
    Ok(())
}

fn clear_model_ref_from_projects(id: &str) -> Result<(), String> {
    use crate::models::UpdateProjectInput;
    use crate::services::ConfigStorage;
    let projects = ConfigStorage::get_projects()?;
    for p in projects {
        if p.config.model_preset_id.as_deref() == Some(id)
            || p.config.claude_model_preset_id.as_deref() == Some(id)
            || p.config.codex_model_preset_id.as_deref() == Some(id)
        {
            let mut new_cfg = p.config.clone();
            if new_cfg.model_preset_id.as_deref() == Some(id) {
                new_cfg.model_preset_id = None;
            }
            if new_cfg.claude_model_preset_id.as_deref() == Some(id) {
                new_cfg.claude_model_preset_id = None;
            }
            if new_cfg.codex_model_preset_id.as_deref() == Some(id) {
                new_cfg.codex_model_preset_id = None;
            }
            let _ = ConfigStorage::update_project(
                &p.id,
                UpdateProjectInput {
                    name: None,
                    working_directory: None,
                    config: Some(new_cfg),
                    is_pinned: None,
                },
            );
        }
    }
    Ok(())
}

// =================================================================
// Migration: legacy project fields -> presets + preset_ids on projects
// =================================================================

/// Auto-name for proxy preset based on URL host:port.
fn name_from_proxy_url(url: &str, fallback_index: usize) -> String {
    let stripped = url
        .trim_start_matches("http://")
        .trim_start_matches("https://")
        .trim_end_matches('/');
    let host_port = stripped.split('/').next().unwrap_or("");
    if host_port.is_empty() {
        format!("代理 {}", fallback_index)
    } else {
        host_port.to_string()
    }
}

fn name_from_model(model: &str, base_url: &str, fallback_index: usize) -> String {
    if !model.is_empty() {
        return model.to_string();
    }
    let stripped = base_url
        .trim_start_matches("http://")
        .trim_start_matches("https://")
        .trim_end_matches('/');
    let host = stripped.split('/').next().unwrap_or("");
    if !host.is_empty() {
        host.to_string()
    } else {
        format!("模型 {}", fallback_index)
    }
}

/// Run once at startup if presets.json doesn't exist:
/// - extract distinct proxy URLs and model triples from projects
/// - create presets, write back preset_ids to projects
/// - keep legacy fields untouched as fallback
pub fn migrate_legacy_to_presets(projects: &mut [Project]) -> Option<GlobalPresets> {
    if PresetsStorage::presets_file_exists() {
        return None;
    }

    let mut presets = GlobalPresets::default();

    // 1) Collect proxies
    for proj in projects.iter() {
        let url = match proj.config.mode.as_str() {
            "claude" => proj.config.proxy.clone(),
            "codex" => proj.config.codex_api_key.clone(),
            _ => String::new(),
        };
        if url.is_empty() {
            continue;
        }
        if presets.proxies.iter().any(|p| p.url == url) {
            continue;
        }
        let idx = presets.proxies.len() + 1;
        let name = ensure_unique_name(
            &name_from_proxy_url(&url, idx),
            presets.proxies.iter().map(|p| p.name.as_str()),
        );
        presets.proxies.push(ProxyPreset {
            id: new_preset_id(),
            name,
            url,
        });
    }

    // 2) Collect models
    for proj in projects.iter() {
        if proj.config.mode != "custom" {
            continue;
        }
        let model = proj.config.model.clone();
        let base_url = proj.config.base_url.clone();
        let token = proj.config.token.clone();
        if model.is_empty() && base_url.is_empty() && token.is_empty() {
            continue;
        }
        if presets
            .models
            .iter()
            .any(|m| m.model == model && m.base_url == base_url && m.token == token)
        {
            continue;
        }
        let idx = presets.models.len() + 1;
        let name = ensure_unique_name(
            &name_from_model(&model, &base_url, idx),
            presets.models.iter().map(|p| p.name.as_str()),
        );
        presets.models.push(ModelPreset {
            id: new_preset_id(),
            name,
            model,
            claude_base_url: String::new(),
            codex_base_url: String::new(),
            base_url,
            token,
            api_format: None,
        });
    }

    // 3) Backfill preset_ids onto projects
    for proj in projects.iter_mut() {
        match proj.config.mode.as_str() {
            "claude" => {
                if !proj.config.proxy.is_empty() && proj.config.claude_proxy_preset_id.is_none() {
                    if let Some(p) = presets.proxies.iter().find(|p| p.url == proj.config.proxy) {
                        proj.config.claude_proxy_preset_id = Some(p.id.clone());
                    }
                }
            }
            "codex" => {
                if !proj.config.codex_api_key.is_empty()
                    && proj.config.codex_proxy_preset_id.is_none()
                {
                    if let Some(p) = presets
                        .proxies
                        .iter()
                        .find(|p| p.url == proj.config.codex_api_key)
                    {
                        proj.config.codex_proxy_preset_id = Some(p.id.clone());
                    }
                }
            }
            "custom" => {
                if proj.config.model_preset_id.is_none()
                    && (!proj.config.model.is_empty()
                        || !proj.config.base_url.is_empty()
                        || !proj.config.token.is_empty())
                {
                    if let Some(m) = presets.models.iter().find(|m| {
                        m.model == proj.config.model
                            && m.base_url == proj.config.base_url
                            && m.token == proj.config.token
                    }) {
                        proj.config.model_preset_id = Some(m.id.clone());
                        if proj.config.custom_cli == "codex" {
                            proj.config.codex_model_preset_id = Some(m.id.clone());
                        } else {
                            proj.config.claude_model_preset_id = Some(m.id.clone());
                        }
                    }
                }
            }
            _ => {}
        }
    }

    Some(presets)
}

/// Upgrade single-endpoint presets to shared presets with independent Claude
/// and Codex URLs. References keep their original IDs. Complementary presets
/// created by v1.2.7 are merged when their shared model and token are equal.
pub fn migrate_model_protocols(projects: &mut [Project]) -> Result<bool, String> {
    let mut presets = PresetsStorage::load();
    let changed = migrate_model_protocols_in_memory(&mut presets, projects);
    if changed {
        PresetsStorage::save(&presets)?;
    }
    Ok(changed)
}

fn migrate_model_protocols_in_memory(
    presets: &mut GlobalPresets,
    projects: &mut [Project],
) -> bool {
    let mut changed = false;

    for project in projects.iter_mut().filter(|p| p.config.mode == "custom") {
        if project.config.custom_cli == "codex" {
            if project.config.codex_model_preset_id.is_none() {
                project.config.codex_model_preset_id = project.config.model_preset_id.clone();
                changed |= project.config.codex_model_preset_id.is_some();
            }
        } else if project.config.claude_model_preset_id.is_none() {
            project.config.claude_model_preset_id = project.config.model_preset_id.clone();
            changed |= project.config.claude_model_preset_id.is_some();
        }
    }

    for index in 0..presets.models.len() {
        if !presets.models[index].claude_base_url.is_empty()
            || !presets.models[index].codex_base_url.is_empty()
            || presets.models[index].base_url.is_empty()
        {
            continue;
        }
        let id = presets.models[index].id.clone();
        let mut used_by_claude = false;
        let mut used_by_codex = false;
        for project in projects.iter() {
            if project.config.mode != "custom" {
                continue;
            }
            let active_id = if project.config.custom_cli == "codex" {
                project
                    .config
                    .codex_model_preset_id
                    .as_ref()
                    .or(project.config.model_preset_id.as_ref())
            } else {
                project
                    .config
                    .claude_model_preset_id
                    .as_ref()
                    .or(project.config.model_preset_id.as_ref())
            };
            if active_id.map(|value| value == &id).unwrap_or(false) {
                if project.config.custom_cli == "codex" {
                    used_by_codex = true;
                } else {
                    used_by_claude = true;
                }
            }
        }

        let legacy_url = presets.models[index].base_url.clone();
        match presets.models[index].api_format {
            Some(ModelApiFormat::OpenaiResponses) => {
                presets.models[index].codex_base_url = legacy_url;
            }
            Some(ModelApiFormat::AnthropicMessages) => {
                presets.models[index].claude_base_url = legacy_url;
            }
            None if used_by_claude && used_by_codex => {
                presets.models[index].claude_base_url = legacy_url.clone();
                presets.models[index].codex_base_url = legacy_url;
            }
            None if used_by_codex => {
                presets.models[index].codex_base_url = legacy_url;
            }
            None => {
                presets.models[index].claude_base_url = legacy_url;
            }
        }
        changed = true;
    }

    let mut keep = 0;
    while keep < presets.models.len() {
        let mut candidate = keep + 1;
        while candidate < presets.models.len() {
            let left = &presets.models[keep];
            let right = &presets.models[candidate];
            let same_shared_values = left.model == right.model && left.token == right.token;
            let complementary = (left.supports(ModelApiFormat::AnthropicMessages)
                && !left.supports(ModelApiFormat::OpenaiResponses)
                && !right.supports(ModelApiFormat::AnthropicMessages)
                && right.supports(ModelApiFormat::OpenaiResponses))
                || (!left.supports(ModelApiFormat::AnthropicMessages)
                    && left.supports(ModelApiFormat::OpenaiResponses)
                    && right.supports(ModelApiFormat::AnthropicMessages)
                    && !right.supports(ModelApiFormat::OpenaiResponses));
            if !same_shared_values || !complementary {
                candidate += 1;
                continue;
            }

            let removed_id = presets.models[candidate].id.clone();
            let kept_id = presets.models[keep].id.clone();
            let candidate_claude = presets.models[candidate]
                .endpoint(ModelApiFormat::AnthropicMessages)
                .to_string();
            let candidate_codex = presets.models[candidate]
                .endpoint(ModelApiFormat::OpenaiResponses)
                .to_string();
            if presets.models[keep].claude_base_url.is_empty() {
                presets.models[keep].claude_base_url = candidate_claude;
            }
            if presets.models[keep].codex_base_url.is_empty() {
                presets.models[keep].codex_base_url = candidate_codex;
            }
            for project in projects.iter_mut() {
                rewire_model_id(&mut project.config, &removed_id, &kept_id);
            }
            if let Some(config) = &mut presets.last_used_config {
                rewire_model_id(config, &removed_id, &kept_id);
            }
            presets.models.remove(candidate);
            changed = true;
        }
        keep += 1;
    }

    changed
}

fn rewire_model_id(config: &mut ProjectConfig, from: &str, to: &str) {
    for field in [
        &mut config.model_preset_id,
        &mut config.claude_model_preset_id,
        &mut config.codex_model_preset_id,
    ] {
        if field.as_deref() == Some(from) {
            *field = Some(to.to_string());
        }
    }
}

#[cfg(test)]
mod model_protocol_migration_tests {
    use super::migrate_model_protocols_in_memory;
    use crate::models::{GlobalPresets, ModelApiFormat, ModelPreset, Project, ProjectConfig};

    fn legacy_preset() -> ModelPreset {
        ModelPreset {
            id: "legacy-model".to_string(),
            name: "Legacy".to_string(),
            model: String::new(),
            claude_base_url: String::new(),
            codex_base_url: String::new(),
            base_url: "https://api.example".to_string(),
            token: "secret".to_string(),
            api_format: None,
        }
    }

    fn custom_project(name: &str, cli: &str) -> Project {
        Project::new(
            name.to_string(),
            ".".to_string(),
            ProjectConfig {
                mode: "custom".to_string(),
                custom_cli: cli.to_string(),
                model_preset_id: Some("legacy-model".to_string()),
                ..ProjectConfig::default()
            },
            false,
        )
    }

    #[test]
    fn claude_only_legacy_preset_keeps_identity_and_moves_its_url() {
        let mut presets = GlobalPresets {
            models: vec![legacy_preset()],
            ..GlobalPresets::default()
        };
        let mut projects = vec![custom_project("Claude", "claude")];

        assert!(migrate_model_protocols_in_memory(
            &mut presets,
            &mut projects
        ));
        assert_eq!(presets.models.len(), 1);
        assert_eq!(
            presets.models[0].claude_base_url,
            "https://api.example"
        );
        assert!(presets.models[0].codex_base_url.is_empty());
        assert_eq!(
            projects[0].config.claude_model_preset_id.as_deref(),
            Some("legacy-model")
        );
    }

    #[test]
    fn codex_only_legacy_preset_moves_its_url() {
        let mut presets = GlobalPresets {
            models: vec![legacy_preset()],
            ..GlobalPresets::default()
        };
        let mut projects = vec![custom_project("Codex", "codex")];

        assert!(migrate_model_protocols_in_memory(
            &mut presets,
            &mut projects
        ));
        assert_eq!(presets.models.len(), 1);
        assert!(presets.models[0].claude_base_url.is_empty());
        assert_eq!(presets.models[0].codex_base_url, "https://api.example");
        assert_eq!(
            projects[0].config.codex_model_preset_id.as_deref(),
            Some("legacy-model")
        );
    }

    #[test]
    fn shared_legacy_preset_keeps_one_identity_and_supports_both_clis() {
        let mut presets = GlobalPresets {
            models: vec![legacy_preset()],
            ..GlobalPresets::default()
        };
        let mut projects = vec![
            custom_project("Claude", "claude"),
            custom_project("Codex", "codex"),
        ];

        assert!(migrate_model_protocols_in_memory(
            &mut presets,
            &mut projects
        ));
        assert_eq!(presets.models.len(), 1);
        assert_eq!(presets.models[0].claude_base_url, "https://api.example");
        assert_eq!(presets.models[0].codex_base_url, "https://api.example");
        assert_eq!(
            projects[0].config.claude_model_preset_id.as_deref(),
            Some("legacy-model")
        );
        assert_eq!(
            projects[1].config.codex_model_preset_id.as_deref(),
            Some("legacy-model")
        );
        assert_eq!(
            projects[1].config.model_preset_id.as_deref(),
            Some("legacy-model")
        );
    }

    #[test]
    fn typed_single_endpoint_preset_is_upgraded_once() {
        let mut preset = legacy_preset();
        preset.api_format = Some(ModelApiFormat::AnthropicMessages);
        let mut presets = GlobalPresets {
            models: vec![preset],
            ..GlobalPresets::default()
        };
        let mut projects = Vec::new();

        assert!(migrate_model_protocols_in_memory(
            &mut presets,
            &mut projects
        ));
        assert_eq!(presets.models[0].claude_base_url, "https://api.example");
        assert!(!migrate_model_protocols_in_memory(
            &mut presets,
            &mut projects
        ));
        assert_eq!(presets.models.len(), 1);
    }

    #[test]
    fn complementary_v127_presets_merge_and_rewire_projects() {
        let mut claude = legacy_preset();
        claude.api_format = Some(ModelApiFormat::AnthropicMessages);
        let mut codex = legacy_preset();
        codex.id = "codex-copy".to_string();
        codex.name = "Legacy (Codex)".to_string();
        codex.base_url = "https://api.example/v1".to_string();
        codex.api_format = Some(ModelApiFormat::OpenaiResponses);
        let mut presets = GlobalPresets {
            models: vec![claude, codex],
            ..GlobalPresets::default()
        };
        let mut projects = vec![custom_project("Claude", "claude"), custom_project("Codex", "codex")];
        projects[1].config.model_preset_id = Some("codex-copy".to_string());
        projects[1].config.codex_model_preset_id = Some("codex-copy".to_string());

        assert!(migrate_model_protocols_in_memory(&mut presets, &mut projects));
        assert_eq!(presets.models.len(), 1);
        assert_eq!(presets.models[0].claude_base_url, "https://api.example");
        assert_eq!(presets.models[0].codex_base_url, "https://api.example/v1");
        assert_eq!(projects[1].config.codex_model_preset_id.as_deref(), Some("legacy-model"));
    }
}
