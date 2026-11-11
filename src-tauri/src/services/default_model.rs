use crate::models::{ModelApiFormat, ModelPreset, Project, ProjectConfig};
use super::{configuration_guard::ConfigurationGuard, ConfigStorage, PresetsStorage};

fn is_unconfigured(config: &ProjectConfig) -> bool {
    config.mode == "claude"
        && config.custom_cli == "claude"
        && [&config.proxy, &config.model, &config.base_url, &config.token, &config.codex_api_key]
            .iter().all(|value| value.trim().is_empty())
        && [&config.proxy_preset_id, &config.claude_proxy_preset_id, &config.codex_proxy_preset_id,
            &config.model_preset_id, &config.claude_model_preset_id, &config.codex_model_preset_id]
            .iter().all(|value| value.as_deref().unwrap_or("").trim().is_empty())
}

pub fn can_apply() -> Result<bool, String> {
    let _guard = ConfigurationGuard::acquire()?;
    Ok(ConfigStorage::get_projects()?.iter().any(|project| project.is_default && is_unconfigured(&project.config)))
}

fn configure(project: &mut Project, preset: &ModelPreset, cli: &str) -> Result<(), String> {
    if !project.is_default || !is_unconfigured(&project.config) {
        return Err("默认项目已有配置，本次未覆盖。可打开默认项目配置手动选择模型。".into());
    }
    let format = match cli {
        "claude" => ModelApiFormat::AnthropicMessages,
        "codex" => ModelApiFormat::OpenaiResponses,
        _ => return Err("不支持的启动方式".into()),
    };
    let endpoint = preset.endpoint(format).trim();
    if !preset.supports(format) || !(endpoint.starts_with("https://") || endpoint.starts_with("http://")) {
        return Err("该模型未配置所选启动方式的有效地址，请重新打开管理模型检查。".into());
    }
    if cli == "codex" && preset.model.trim().is_empty() {
        return Err("Codex 配置缺少模型名称".into());
    }
    project.config.mode = "custom".into();
    project.config.custom_cli = cli.into();
    if cli == "claude" {
        project.config.claude_model_preset_id = Some(preset.id.clone());
    } else {
        project.config.codex_model_preset_id = Some(preset.id.clone());
    }
    project.updated_at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs();
    Ok(())
}

pub fn apply(preset_id: &str, cli: &str) -> Result<Project, String> {
    // Re-read and save under the existing shared lock: a dashboard edit between
    // showing the prompt and confirming must never be overwritten.
    let _guard = ConfigurationGuard::acquire()?;
    let mut config = ConfigStorage::load_config_v2()?;
    let presets = PresetsStorage::load();
    let preset = presets.models.iter().find(|preset| preset.id == preset_id)
        .ok_or("模型配置已不存在，请重新打开管理模型检查。")?;
    let project = config.projects.iter_mut().find(|project| project.is_default)
        .ok_or("默认项目不存在")?;
    configure(project, preset, cli)?;
    let saved = project.clone();
    ConfigStorage::save_config_v2(&config)?;
    Ok(saved)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn preset() -> ModelPreset {
        ModelPreset { id: "preset".into(), name: "test".into(), model: "model".into(),
            claude_base_url: "https://example.com/claude".into(), codex_base_url: "https://example.com/codex".into(),
            base_url: String::new(), token: "test".into(), api_format: None }
    }

    fn project() -> Project {
        Project::new("default".into(), "workdir".into(), ProjectConfig::default(), true)
    }

    #[test]
    fn chooses_matching_cli_and_reference() {
        for cli in ["claude", "codex"] {
            let mut project = project();
            project.config.skip_permissions = false;
            configure(&mut project, &preset(), cli).unwrap();
            assert_eq!(project.config.mode, "custom");
            assert_eq!(project.config.custom_cli, cli);
            assert_eq!(project.config.claude_model_preset_id.as_deref(), if cli == "claude" { Some("preset") } else { None });
            assert_eq!(project.config.codex_model_preset_id.as_deref(), if cli == "codex" { Some("preset") } else { None });
            assert!(!project.config.skip_permissions);
            assert_eq!(project.working_directory, "workdir");
            assert!(configure(&mut project, &preset(), cli).is_err());
        }
    }

    #[test]
    fn rejects_incompatible_or_invalid_model_without_mutation() {
        for cli in ["claude", "codex", "unknown"] {
            let mut project = project();
            let mut preset = preset();
            if cli == "claude" { preset.claude_base_url.clear(); } else { preset.codex_base_url.clear(); }
            assert!(configure(&mut project, &preset, cli).is_err());
            assert!(is_unconfigured(&project.config));
        }
        let mut preset = preset();
        preset.model.clear();
        assert!(configure(&mut project(), &preset, "codex").is_err());
    }

    #[test]
    fn preserves_existing_settings_including_inactive_cli_and_legacy_fields() {
        for field in ["proxy", "model", "base_url", "token", "codex_api_key", "proxy_preset_id",
            "claude_proxy_preset_id", "codex_proxy_preset_id", "model_preset_id",
            "claude_model_preset_id", "codex_model_preset_id", "mode", "custom_cli"] {
            let mut value = serde_json::to_value(project()).unwrap();
            value["config"][field] = serde_json::json!("existing");
            let mut project: Project = serde_json::from_value(value.clone()).unwrap();
            assert!(configure(&mut project, &preset(), "claude").is_err(), "{field}");
            assert_eq!(serde_json::to_value(project).unwrap(), value);
        }
        let mut project = project();
        project.is_default = false;
        assert!(configure(&mut project, &preset(), "claude").is_err());
    }
}
