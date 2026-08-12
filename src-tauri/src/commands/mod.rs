use crate::models::{
    CreateProjectInput, GlobalPresets, ModelApiFormat, ModelPreset, PinnedOrderItem, Project,
    ProjectConfig, ProjectOrderItem, ProxyPreset, UpdateProjectInput,
};
use crate::services::cc_config_checker::{CleanTarget, ConfigScanResult, ProjectInfo};
use crate::services::*;
use std::collections::HashMap;
use std::path::Path;

#[tauri::command]
pub async fn check_nodejs() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_nodejs())
}

#[tauri::command]
pub async fn check_claude() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_claude())
}

#[tauri::command]
pub async fn check_nodejs_with_update() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_nodejs_with_update().await)
}

#[tauri::command]
pub async fn check_claude_with_update() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_claude_with_update().await)
}

#[tauri::command]
pub async fn check_gitbash() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_gitbash())
}

#[tauri::command]
pub async fn check_gitbash_with_update() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_gitbash_with_update().await)
}

#[tauri::command]
pub fn refresh_system_path() {
    #[cfg(windows)]
    DependencyChecker::refresh_system_path();
}

#[tauri::command]
pub async fn install_nodejs() -> Result<(), String> {
    Installer::install_nodejs()
}

#[tauri::command]
pub async fn update_nodejs() -> Result<(), String> {
    Installer::update_nodejs()
}

#[tauri::command]
pub async fn install_claude() -> Result<(), String> {
    Installer::install_claude()
}

#[tauri::command]
pub async fn update_claude() -> Result<(), String> {
    Installer::update_claude()
}

#[tauri::command]
pub async fn install_gitbash() -> Result<(), String> {
    Installer::install_gitbash()
}

#[tauri::command]
pub async fn update_gitbash() -> Result<(), String> {
    Installer::update_gitbash()
}

#[tauri::command]
pub async fn check_codex() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_codex())
}

#[tauri::command]
pub async fn check_codex_with_update() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(DependencyChecker::check_codex_with_update().await)
}

#[tauri::command]
pub async fn install_codex() -> Result<(), String> {
    Installer::install_codex()
}

#[tauri::command]
pub async fn update_codex() -> Result<(), String> {
    Installer::update_codex()
}

#[tauri::command]
pub async fn reinstall_claude() -> Result<(), String> {
    Installer::reinstall_claude()
}

#[tauri::command]
pub async fn reinstall_codex() -> Result<(), String> {
    Installer::reinstall_codex()
}

#[tauri::command]
pub async fn check_skill_market() -> Result<dependency_checker::DependencyStatus, String> {
    Ok(Installer::check_skill_market())
}

/// Silent background updates (no terminal window). Used by auto-update after
/// the background check detects a new version; failure falls back to the
/// manual "有更新可用" badge.
#[tauri::command]
pub async fn update_claude_silent() -> Result<(), String> {
    Installer::npm_update_silent("@anthropic-ai/claude-code").await
}

#[tauri::command]
pub async fn update_codex_silent() -> Result<(), String> {
    Installer::npm_update_silent("@openai/codex").await
}

/// Local check + a fast intranet probe (3s timeout) for package updates.
/// External users without intranet access just get the local status back.
#[tauri::command]
pub async fn check_skill_market_with_update() -> Result<dependency_checker::DependencyStatus, String>
{
    Ok(Installer::check_skill_market_with_update().await)
}

/// Best-effort install. Has a built-in timeout (15s); on failure the wizard treats
/// it as 'skipped' rather than 'error' since the marketplace is intranet-only.
#[tauri::command]
pub async fn install_skill_market() -> Result<(), String> {
    // Run blocking IO off the tauri runtime so the UI stays responsive.
    tokio::task::spawn_blocking(|| Installer::install_skill_market())
        .await
        .map_err(|e| format!("任务调度失败: {}", e))?
}

#[tauri::command]
pub async fn launch_claude_code(config: HashMap<String, String>) -> Result<(), String> {
    // Launch involves blocking subprocess calls (where.exe / npm checks); keep them
    // off the tauri runtime so the UI stays responsive.
    tokio::task::spawn_blocking(move || Launcher::launch_with_config(config))
        .await
        .map_err(|e| format!("任务调度失败: {}", e))?
}

#[tauri::command]
pub fn generate_powershell_command(config: HashMap<String, String>) -> String {
    Launcher::generate_powershell_command(&config)
}

#[tauri::command]
pub fn generate_cmd_command(config: HashMap<String, String>) -> String {
    Launcher::generate_cmd_command(&config)
}

#[tauri::command]
pub fn generate_bash_command(config: HashMap<String, String>) -> String {
    Launcher::generate_bash_command(&config)
}

#[tauri::command]
pub fn get_platform() -> String {
    #[cfg(windows)]
    return "windows".to_string();
    #[cfg(target_os = "macos")]
    return "macos".to_string();
    #[cfg(target_os = "linux")]
    return "linux".to_string();
    #[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
    return "unknown".to_string();
}

#[tauri::command]
pub fn save_to_settings(config: HashMap<String, String>) -> Result<(), String> {
    SettingsManager::save_config(config)
}

#[tauri::command]
pub fn reset_settings() -> Result<(), String> {
    SettingsManager::reset_config()
}

#[tauri::command]
pub fn open_settings_file() -> Result<(), String> {
    SettingsManager::open_settings_file()
}

#[tauri::command]
pub fn save_app_config(config: AppConfig) -> Result<(), String> {
    ConfigStorage::save_config(&config)
}

#[tauri::command]
pub fn load_app_config() -> Result<AppConfig, String> {
    ConfigStorage::load_config()
}

// ============ New Project Management Commands ============

#[tauri::command]
pub fn get_projects() -> Result<Vec<Project>, String> {
    ConfigStorage::get_projects()
}

#[tauri::command]
pub fn get_project(id: String) -> Result<Project, String> {
    ConfigStorage::get_project(&id)
}

#[tauri::command]
pub fn create_project(
    name: String,
    working_directory: String,
    config: ProjectConfig,
) -> Result<Project, String> {
    let input = CreateProjectInput {
        name,
        working_directory,
        config,
    };
    ConfigStorage::create_project(input)
}

#[tauri::command]
pub fn update_project(
    id: String,
    name: Option<String>,
    working_directory: Option<String>,
    config: Option<ProjectConfig>,
    is_pinned: Option<bool>,
) -> Result<Project, String> {
    let updates = UpdateProjectInput {
        name,
        working_directory,
        config,
        is_pinned,
    };
    ConfigStorage::update_project(&id, updates)
}

#[tauri::command]
pub fn delete_project(id: String) -> Result<(), String> {
    ConfigStorage::delete_project(&id)
}

#[tauri::command]
pub async fn launch_project(id: String) -> Result<(), String> {
    // Launch involves blocking subprocess calls (where.exe / npm checks, possibly an
    // npm shim repair taking seconds); keep them off the tauri runtime so the UI
    // stays responsive.
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        let project = ConfigStorage::get_project(&id)?;
        validate_project_configuration(&project)?;
        let config = build_config_map(&project);

        // Launch with working directory
        Launcher::launch_with_config_and_dir(config, Some(project.working_directory.clone()))?;

        // Update last launched timestamp
        let _ = ConfigStorage::update_project_launched(&id);

        Ok(())
    })
    .await
    .map_err(|e| format!("任务调度失败: {}", e))?
}

#[tauri::command]
pub fn open_project_folder(id: String) -> Result<(), String> {
    let project = ConfigStorage::get_project(&id)?;
    let folder = Path::new(&project.working_directory);

    if !folder.exists() {
        return Err(format!("项目文件夹不存在: {}", folder.display()));
    }
    if !folder.is_dir() {
        return Err(format!("项目路径不是文件夹: {}", folder.display()));
    }

    tauri_plugin_opener::open_path(folder, None::<&str>)
        .map_err(|e| format!("系统无法打开该文件夹: {}", e))
}

#[tauri::command]
pub async fn select_directory(app_handle: tauri::AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    let result = app_handle
        .dialog()
        .file()
        .set_title("选择项目目录")
        .blocking_pick_folder();

    Ok(result.map(|p| p.to_string()))
}

#[tauri::command]
pub fn generate_project_powershell_command(id: String) -> Result<String, String> {
    let project = ConfigStorage::get_project(&id)?;
    let config = build_config_map(&project);
    Ok(Launcher::generate_powershell_command_with_dir(
        &config,
        Some(project.working_directory),
    ))
}

#[tauri::command]
pub fn generate_project_cmd_command(id: String) -> Result<String, String> {
    let project = ConfigStorage::get_project(&id)?;
    let config = build_config_map(&project);
    Ok(Launcher::generate_cmd_command_with_dir(
        &config,
        Some(project.working_directory),
    ))
}

#[tauri::command]
pub fn generate_project_bash_command(id: String) -> Result<String, String> {
    let project = ConfigStorage::get_project(&id)?;
    let config = build_config_map(&project);
    Ok(Launcher::generate_bash_command_with_dir(
        &config,
        Some(project.working_directory),
    ))
}

/// Resolve effective proxy URL: preset wins, legacy field is fallback.
fn resolve_proxy(project: &Project, presets: &crate::models::GlobalPresets) -> String {
    let preset_id = match project.config.mode.as_str() {
        "claude" => project
            .config
            .claude_proxy_preset_id
            .as_ref()
            .or(project.config.proxy_preset_id.as_ref()),
        "codex" => project
            .config
            .codex_proxy_preset_id
            .as_ref()
            .or(project.config.proxy_preset_id.as_ref()),
        _ => None,
    };
    if let Some(id) = preset_id {
        if let Some(p) = presets.proxies.iter().find(|p| &p.id == id) {
            return p.url.clone();
        }
    }
    match project.config.mode.as_str() {
        "claude" => project.config.proxy.clone(),
        "codex" => project.config.codex_api_key.clone(),
        _ => String::new(),
    }
}

/// Resolve effective (model, base_url, token) for custom mode: preset wins, legacy fields fallback.
fn resolve_model(
    project: &Project,
    presets: &crate::models::GlobalPresets,
) -> (String, String, String) {
    let preset_id = if project.config.custom_cli == "codex" {
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
    if let Some(id) = preset_id {
        if let Some(m) = presets.models.iter().find(|m| &m.id == id) {
            let format = if project.config.custom_cli == "codex" {
                ModelApiFormat::OpenaiResponses
            } else {
                ModelApiFormat::AnthropicMessages
            };
            return (
                m.model.clone(),
                m.endpoint(format).to_string(),
                m.token.clone(),
            );
        }
    }
    (
        project.config.model.clone(),
        project.config.base_url.clone(),
        project.config.token.clone(),
    )
}

fn build_config_map(project: &Project) -> HashMap<String, String> {
    let mut config: HashMap<String, String> = HashMap::new();
    let presets = PresetsStorage::load();

    match project.config.mode.as_str() {
        "claude" => {
            let proxy = resolve_proxy(project, &presets);
            if !proxy.is_empty() {
                config.insert("HTTP_PROXY".to_string(), proxy.clone());
                config.insert("HTTPS_PROXY".to_string(), proxy);
            }
        }
        "codex" => {
            config.insert("CLI_PROGRAM".to_string(), "codex".to_string());
            let proxy = resolve_proxy(project, &presets);
            if !proxy.is_empty() {
                config.insert("HTTP_PROXY".to_string(), proxy.clone());
                config.insert("HTTPS_PROXY".to_string(), proxy);
            }
        }
        "custom" => {
            let (model, base_url, token) = resolve_model(project, &presets);
            if project.config.custom_cli == "codex" {
                let mut args = vec![
                    "--model".to_string(),
                    model,
                    "-c".to_string(),
                    "model_provider=\"cc_launcher\"".to_string(),
                    "-c".to_string(),
                    "model_providers.cc_launcher.name=\"CC Launcher\"".to_string(),
                    "-c".to_string(),
                    format!(
                        "model_providers.cc_launcher.base_url={}",
                        serde_json::to_string(&base_url).unwrap_or_else(|_| "\"\"".to_string())
                    ),
                    "-c".to_string(),
                    "model_providers.cc_launcher.wire_api=\"responses\"".to_string(),
                    // Unknown/custom model ids inherit the user's global Codex effort. A
                    // global `xhigh` is valid for some OpenAI models, but many compatible
                    // gateways (including LiteLLM-backed GLM) only accept up to `high`.
                    // Pin a broadly supported value for launcher-managed custom providers.
                    "-c".to_string(),
                    "model_reasoning_effort=\"high\"".to_string(),
                ];
                if !token.is_empty() {
                    args.push("-c".to_string());
                    args.push(
                        "model_providers.cc_launcher.env_key=\"CCL_CODEX_API_KEY\"".to_string(),
                    );
                    config.insert("CCL_CODEX_API_KEY".to_string(), token);
                }
                config.insert("CLI_PROGRAM".to_string(), "codex".to_string());
                config.insert(
                    "CLI_ARGS_JSON".to_string(),
                    serde_json::to_string(&args).unwrap_or_else(|_| "[]".to_string()),
                );
                config.insert("CODEX_CUSTOM_PROVIDER".to_string(), "true".to_string());
            } else {
                if !model.is_empty() {
                    config.insert("ANTHROPIC_MODEL".to_string(), model);
                }
                if !base_url.is_empty() {
                    config.insert("ANTHROPIC_BASE_URL".to_string(), base_url);
                }
                if !token.is_empty() {
                    config.insert("ANTHROPIC_AUTH_TOKEN".to_string(), token);
                }
            }
        }
        _ => {}
    }

    if project.config.skip_permissions {
        config.insert("SKIP_PERMISSIONS".to_string(), "true".to_string());
    }

    config
}

#[tauri::command]
pub fn get_home_directory() -> Result<String, String> {
    dirs::home_dir()
        .map(|p| p.to_string_lossy().to_string())
        .ok_or_else(|| "无法获取用户主目录".to_string())
}

#[tauri::command]
pub fn update_projects_order(orders: Vec<ProjectOrderItem>) -> Result<(), String> {
    ConfigStorage::update_projects_order(orders)
}

#[tauri::command]
pub fn update_pinned_order(orders: Vec<PinnedOrderItem>) -> Result<(), String> {
    ConfigStorage::update_pinned_order(orders)
}

#[tauri::command]
pub fn toggle_project_pinned(id: String, is_pinned: bool) -> Result<Project, String> {
    ConfigStorage::toggle_project_pinned(&id, is_pinned)
}

// ============ Onboarding Commands ============

#[tauri::command]
pub fn get_onboarding_status() -> Result<bool, String> {
    ConfigStorage::get_onboarding_status()
}

#[tauri::command]
pub fn set_onboarding_completed() -> Result<(), String> {
    ConfigStorage::set_onboarding_completed()
}

// ============ Claude Login Check Commands ============

#[tauri::command]
pub fn check_claude_login() -> bool {
    if let Some(home) = dirs::home_dir() {
        let claude_dir = home.join(".claude");
        claude_dir.exists() && claude_dir.is_dir()
    } else {
        false
    }
}

#[tauri::command]
pub async fn launch_claude_for_login(proxy: Option<String>) -> Result<(), String> {
    // Same as launch_project: blocking subprocess calls go off the tauri runtime.
    tokio::task::spawn_blocking(move || -> Result<(), String> {
        let mut config: HashMap<String, String> = HashMap::new();
        if let Some(p) = proxy {
            if !p.is_empty() {
                config.insert("HTTP_PROXY".to_string(), p.clone());
                config.insert("HTTPS_PROXY".to_string(), p);
            }
        }
        let home_dir = dirs::home_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "~".to_string());
        Launcher::launch_with_config_and_dir(config, Some(home_dir))
    })
    .await
    .map_err(|e| format!("任务调度失败: {}", e))?
}

// ============ CC Config Checker Commands ============

#[tauri::command]
pub fn scan_cc_config(projects: Vec<ProjectInfo>) -> ConfigScanResult {
    CcConfigChecker::scan_all(&projects)
}

#[tauri::command]
pub fn clean_cc_config_field(file_path: String, key: String) -> Result<(), String> {
    CcConfigChecker::clean_field(&file_path, &key)
}

#[tauri::command]
pub fn clean_cc_config_all(targets: Vec<CleanTarget>) -> Result<u32, String> {
    CcConfigChecker::clean_all(&targets)
}

#[tauri::command]
pub fn open_cc_config_file(file_path: String) -> Result<(), String> {
    CcConfigChecker::open_file(&file_path)
}

#[tauri::command]
pub fn fix_cc_config_bom(file_path: String) -> Result<(), String> {
    CcConfigChecker::fix_bom(&file_path)
}

#[tauri::command]
pub fn fix_cc_mcp_misplaced(file_path: String, target_path: String) -> Result<(), String> {
    CcConfigChecker::fix_mcp_misplaced(&file_path, &target_path)
}

#[tauri::command]
pub fn remove_cc_mcp_servers(file_path: String) -> Result<(), String> {
    CcConfigChecker::remove_mcp_servers(&file_path)
}

// ============ Global Presets Commands ============

#[tauri::command]
pub fn get_global_presets() -> GlobalPresets {
    PresetsStorage::load()
}

#[tauri::command]
pub fn create_proxy_preset(name: String, url: String) -> Result<ProxyPreset, String> {
    PresetsStorage::create_proxy(name, url)
}

#[tauri::command]
pub fn update_proxy_preset(id: String, name: String, url: String) -> Result<ProxyPreset, String> {
    PresetsStorage::update_proxy(&id, name, url)
}

#[tauri::command]
pub fn delete_proxy_preset(id: String) -> Result<(), String> {
    PresetsStorage::delete_proxy(&id)
}

#[tauri::command]
pub fn count_proxy_preset_refs(id: String) -> usize {
    PresetsStorage::count_proxy_refs(&id)
}

#[tauri::command]
pub fn create_model_preset(
    name: String,
    model: String,
    claude_base_url: String,
    codex_base_url: String,
    token: String,
) -> Result<ModelPreset, String> {
    validate_model_endpoints(&model, &claude_base_url, &codex_base_url)?;
    PresetsStorage::create_model(name, model, claude_base_url, codex_base_url, token)
}

#[tauri::command]
pub fn update_model_preset(
    id: String,
    name: String,
    model: String,
    claude_base_url: String,
    codex_base_url: String,
    token: String,
) -> Result<ModelPreset, String> {
    validate_model_endpoints(&model, &claude_base_url, &codex_base_url)?;
    PresetsStorage::update_model(
        &id,
        name,
        model,
        claude_base_url,
        codex_base_url,
        token,
    )
}

#[cfg(test)]
mod preset_resolution_tests {
    use super::{build_config_map, resolve_model, resolve_proxy};
    use crate::models::{
        GlobalPresets, ModelApiFormat, ModelPreset, Project, ProjectConfig, ProxyPreset,
    };

    #[test]
    fn resolves_claude_and_codex_proxies_independently() {
        let presets = GlobalPresets {
            proxies: vec![
                ProxyPreset {
                    id: "claude-proxy".to_string(),
                    name: "Claude proxy".to_string(),
                    url: "http://127.0.0.1:7890".to_string(),
                },
                ProxyPreset {
                    id: "codex-proxy".to_string(),
                    name: "Codex proxy".to_string(),
                    url: "http://127.0.0.1:7891".to_string(),
                },
            ],
            ..GlobalPresets::default()
        };
        let config = ProjectConfig {
            mode: "claude".to_string(),
            claude_proxy_preset_id: Some("claude-proxy".to_string()),
            codex_proxy_preset_id: Some("codex-proxy".to_string()),
            ..ProjectConfig::default()
        };
        let mut project = Project::new("proxy-test".to_string(), ".".to_string(), config, false);

        assert_eq!(resolve_proxy(&project, &presets), "http://127.0.0.1:7890");
        project.config.mode = "codex".to_string();
        assert_eq!(resolve_proxy(&project, &presets), "http://127.0.0.1:7891");
    }

    #[test]
    fn resolves_model_from_the_active_cli_only() {
        let presets = GlobalPresets {
            models: vec![
                ModelPreset {
                    id: "claude-model".to_string(),
                    name: "Claude".to_string(),
                    model: "claude-custom".to_string(),
                    claude_base_url: "https://claude.example".to_string(),
                    codex_base_url: String::new(),
                    base_url: "https://claude.example/v1".to_string(),
                    token: "claude-token".to_string(),
                    api_format: Some(ModelApiFormat::AnthropicMessages),
                },
                ModelPreset {
                    id: "codex-model".to_string(),
                    name: "Codex".to_string(),
                    model: "gpt-custom".to_string(),
                    claude_base_url: String::new(),
                    codex_base_url: "https://codex.example/v1".to_string(),
                    base_url: "https://codex.example/v1".to_string(),
                    token: "codex-token".to_string(),
                    api_format: Some(ModelApiFormat::OpenaiResponses),
                },
            ],
            ..GlobalPresets::default()
        };
        let config = ProjectConfig {
            mode: "custom".to_string(),
            custom_cli: "codex".to_string(),
            claude_model_preset_id: Some("claude-model".to_string()),
            codex_model_preset_id: Some("codex-model".to_string()),
            ..ProjectConfig::default()
        };
        let project = Project::new("model-test".to_string(), ".".to_string(), config, false);

        assert_eq!(
            resolve_model(&project, &presets),
            (
                "gpt-custom".to_string(),
                "https://codex.example/v1".to_string(),
                "codex-token".to_string(),
            )
        );
    }

    #[test]
    fn one_shared_model_resolves_each_cli_specific_url() {
        let presets = GlobalPresets {
            models: vec![ModelPreset {
                id: "shared-model".to_string(),
                name: "Shared".to_string(),
                model: "shared-model-name".to_string(),
                claude_base_url: "https://gateway.example/anthropic".to_string(),
                codex_base_url: "https://gateway.example/v1".to_string(),
                base_url: String::new(),
                token: "shared-token".to_string(),
                api_format: None,
            }],
            ..GlobalPresets::default()
        };
        let config = ProjectConfig {
            mode: "custom".to_string(),
            custom_cli: "claude".to_string(),
            claude_model_preset_id: Some("shared-model".to_string()),
            codex_model_preset_id: Some("shared-model".to_string()),
            ..ProjectConfig::default()
        };
        let mut project = Project::new("shared".to_string(), ".".to_string(), config, false);

        assert_eq!(
            resolve_model(&project, &presets).1,
            "https://gateway.example/anthropic"
        );
        project.config.custom_cli = "codex".to_string();
        assert_eq!(
            resolve_model(&project, &presets).1,
            "https://gateway.example/v1"
        );
    }

    #[test]
    fn custom_codex_overrides_incompatible_global_reasoning_effort() {
        let config = ProjectConfig {
            mode: "custom".to_string(),
            custom_cli: "codex".to_string(),
            model: "glm-5.2".to_string(),
            base_url: "https://gateway.example/v1".to_string(),
            token: "secret".to_string(),
            ..ProjectConfig::default()
        };
        let project = Project::new("codex-custom".to_string(), ".".to_string(), config, false);

        let launch_config = build_config_map(&project);
        let args: Vec<String> = serde_json::from_str(&launch_config["CLI_ARGS_JSON"]).unwrap();

        assert!(args.windows(2).any(|pair| {
            pair == ["-c".to_string(), "model_reasoning_effort=\"high\"".to_string()]
        }));
    }
}

#[tauri::command]
pub fn delete_model_preset(id: String) -> Result<(), String> {
    PresetsStorage::delete_model(&id)
}

#[tauri::command]
pub fn count_model_preset_refs(id: String) -> usize {
    PresetsStorage::count_model_refs(&id)
}

#[derive(serde::Serialize)]
pub struct ModelProbeResult {
    pub ok: bool,
    pub status: u16,
    pub latency_ms: u64,
    pub models: Vec<String>,
    pub error: Option<String>,
}

fn validate_model_base_url(base_url: &str) -> Result<(), String> {
    let trimmed = base_url.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        return Err("请先配置 API Base URL".to_string());
    }

    let lower = trimmed.to_ascii_lowercase();
    if !lower.starts_with("https://") && !lower.starts_with("http://") {
        return Err("请填写有效的 HTTP(S) Base URL".to_string());
    }
    Ok(())
}

fn validate_model_endpoints(
    model: &str,
    claude_base_url: &str,
    codex_base_url: &str,
) -> Result<(), String> {
    if claude_base_url.trim().is_empty() && codex_base_url.trim().is_empty() {
        return Err("Claude 和 Codex 地址至少填写一个".to_string());
    }
    if !claude_base_url.trim().is_empty() {
        validate_model_base_url(claude_base_url)?;
    }
    if !codex_base_url.trim().is_empty() {
        validate_model_base_url(codex_base_url)?;
        if model.trim().is_empty() {
            return Err("配置 Codex 地址时必须填写模型名称".to_string());
        }
    }
    Ok(())
}

fn protocol_probe_succeeded(status: u16) -> bool {
    (200..=299).contains(&status)
}

#[tauri::command]
#[allow(non_snake_case)]
pub async fn probe_model_endpoint(
    baseUrl: String,
    token: String,
    model: String,
    apiFormat: ModelApiFormat,
) -> Result<ModelProbeResult, String> {
    use std::time::{Duration, Instant};

    let trimmed = baseUrl.trim().trim_end_matches('/').to_string();
    if let Err(error) = validate_model_base_url(&trimmed) {
        return Ok(ModelProbeResult {
            ok: false,
            status: 0,
            latency_ms: 0,
            models: vec![],
            error: Some(error),
        });
    }
    let model = model.trim().to_string();
    if model.is_empty() {
        return Ok(ModelProbeResult {
            ok: false,
            status: 0,
            latency_ms: 0,
            models: vec![],
            error: Some("请先填写模型名称，再进行真实兼容性检测".to_string()),
        });
    }

    if matches!(apiFormat, ModelApiFormat::OpenaiResponses) {
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_secs(20))
            .build()
        {
            Ok(client) => client,
            Err(error) => {
                return Ok(ModelProbeResult {
                    ok: false,
                    status: 0,
                    latency_ms: 0,
                    models: vec![],
                    error: Some(format!("构造 HTTP client 失败: {}", error)),
                })
            }
        };
        let tok = token.trim();
        let responses_url = format!("{}/responses", trimmed);
        let mut request = client.post(&responses_url).json(&serde_json::json!({
            "model": model,
            "input": "Reply with OK.",
            "max_output_tokens": 16,
            "stream": false,
            "reasoning": { "effort": "high" },
            "tools": [{
                "type": "function",
                "name": "cc_launcher_probe",
                "description": "Connectivity probe; do not call.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": false
                }
            }],
            "tool_choice": "none"
        }));
        if !tok.is_empty() {
            request = request.bearer_auth(tok);
        }

        let start = Instant::now();
        let response = match request.send().await {
            Ok(response) => response,
            Err(error) => {
                let latency_ms = start.elapsed().as_millis() as u64;
                let message = if error.is_timeout() {
                    "Responses API 实测超时（>20s）".to_string()
                } else if error.is_connect() {
                    format!("无法连接 Responses API: {}", error)
                } else {
                    format!("Responses API 请求失败: {}", error)
                };
                return Ok(ModelProbeResult {
                    ok: false,
                    status: 0,
                    latency_ms,
                    models: vec![],
                    error: Some(message),
                });
            }
        };
        let latency_ms = start.elapsed().as_millis() as u64;
        let status = response.status().as_u16();
        let probe_succeeded = protocol_probe_succeeded(status);
        let body_text = response.text().await.unwrap_or_default();
        if !probe_succeeded {
            let snippet: String = body_text.chars().take(200).collect();
            let error = match status {
                401 | 403 => format!("Responses API 鉴权失败（HTTP {}），请检查 API Key", status),
                404 | 405 => format!(
                    "该地址未提供 Codex 所需的 Responses API（HTTP {}）；仅支持 Anthropic 或 Chat Completions 的地址不能用于 Codex",
                    status
                ),
                501 => "该模型服务未实现 Codex 所需的 Responses API（HTTP 501）".to_string(),
                _ => format!("Responses API HTTP {}: {}", status, snippet),
            };
            return Ok(ModelProbeResult {
                ok: false,
                status,
                latency_ms,
                models: vec![],
                error: Some(error),
            });
        }

        // A successful minimal generation validates the selected model, key, request
        // schema, reasoning setting, and function-tool support. Model discovery is
        // still best-effort because some valid providers do not expose GET /models.
        let mut models_request = client.get(format!("{}/models", trimmed));
        if !tok.is_empty() {
            models_request = models_request.bearer_auth(tok);
        }
        let models = match models_request.send().await {
            Ok(models_response) if models_response.status().is_success() => models_response
                .json::<serde_json::Value>()
                .await
                .ok()
                .and_then(|value| value.get("data").and_then(|data| data.as_array()).cloned())
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| {
                            item.get("id")
                                .and_then(|value| value.as_str())
                                .map(str::to_string)
                        })
                        .collect()
                })
                .unwrap_or_default(),
            _ => vec![],
        };
        return Ok(ModelProbeResult {
            ok: true,
            status,
            latency_ms,
            models,
            error: None,
        });
    }

    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            return Ok(ModelProbeResult {
                ok: false,
                status: 0,
                latency_ms: 0,
                models: vec![],
                error: Some(format!("构造 HTTP client 失败: {}", e)),
            })
        }
    };

    let tok = token.trim();
    let messages_url = format!("{}/v1/messages", trimmed);
    let mut req = client
        .post(&messages_url)
        .header("anthropic-version", "2023-06-01")
        .json(&serde_json::json!({
            "model": model,
            "max_tokens": 1,
            "messages": [{ "role": "user", "content": "Reply with OK." }],
            "stream": false
        }));
    if !tok.is_empty() {
        req = req.bearer_auth(tok).header("x-api-key", tok);
    }

    let start = Instant::now();
    let resp = match req.send().await {
        Ok(r) => r,
        Err(e) => {
            let latency_ms = start.elapsed().as_millis() as u64;
            let msg = if e.is_timeout() {
                "Messages API 实测超时（>20s）".to_string()
            } else if e.is_connect() {
                format!("无法连接 Messages API: {}", e)
            } else {
                format!("Messages API 请求失败: {}", e)
            };
            return Ok(ModelProbeResult {
                ok: false,
                status: 0,
                latency_ms,
                models: vec![],
                error: Some(msg),
            });
        }
    };
    let latency_ms = start.elapsed().as_millis() as u64;
    let status = resp.status().as_u16();
    let probe_succeeded = protocol_probe_succeeded(status);
    let body_text = resp.text().await.unwrap_or_default();
    if !probe_succeeded {
        let snippet: String = body_text.chars().take(200).collect();
        let error = match status {
            401 | 403 => format!("Messages API 鉴权失败（HTTP {}），请检查 API Key", status),
            404 | 405 => format!(
                "该地址未提供 Claude Code 所需的 Messages API（HTTP {}）",
                status
            ),
            501 => "该模型服务未实现 Claude Code 所需的 Messages API（HTTP 501）".to_string(),
            _ => format!("Messages API HTTP {}: {}", status, snippet),
        };
        return Ok(ModelProbeResult {
            ok: false,
            status,
            latency_ms,
            models: vec![],
            error: Some(error),
        });
    }

    // The successful minimal generation validates the selected model, key, and
    // Messages request schema. Model discovery remains best-effort.
    let mut models_request = client
        .get(format!("{}/v1/models", trimmed))
        .header("anthropic-version", "2023-06-01");
    if !tok.is_empty() {
        models_request = models_request.bearer_auth(tok).header("x-api-key", tok);
    }
    let models = match models_request.send().await {
        Ok(models_response) if models_response.status().is_success() => models_response
            .json::<serde_json::Value>()
            .await
            .ok()
            .and_then(|value| value.get("data").and_then(|data| data.as_array()).cloned())
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| {
                        item.get("id")
                            .and_then(|value| value.as_str())
                            .map(str::to_string)
                    })
                    .collect()
            })
            .unwrap_or_default(),
        _ => vec![],
    };

    Ok(ModelProbeResult {
        ok: true,
        status,
        latency_ms,
        models,
        error: None,
    })
}

#[tauri::command]
pub fn get_last_used_project_config() -> Option<ProjectConfig> {
    PresetsStorage::get_last_used()
}

#[tauri::command]
pub fn set_last_used_project_config(config: ProjectConfig) -> Result<(), String> {
    PresetsStorage::set_last_used(config)
}

/// Validate that a project is fully configured before launch.
/// custom mode requires a usable model preset (or legacy fallback fields). Other modes always pass.
#[tauri::command]
pub fn validate_project_launch(id: String) -> Result<(), String> {
    let project = ConfigStorage::get_project(&id)?;
    validate_project_configuration(&project)
}

fn validate_project_configuration(project: &Project) -> Result<(), String> {
    if project.config.mode != "custom" {
        return Ok(());
    }
    let presets = PresetsStorage::load();
    let preset_id = if project.config.custom_cli == "codex" {
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
    let expected_format = if project.config.custom_cli == "codex" {
        ModelApiFormat::OpenaiResponses
    } else {
        ModelApiFormat::AnthropicMessages
    };
    let (model, base_url, _token) = match preset_id {
        Some(pid) => match presets.models.iter().find(|m| &m.id == pid) {
            Some(m) => (
                m.model.clone(),
                m.endpoint(expected_format).to_string(),
                m.token.clone(),
            ),
            None => (
                project.config.model.clone(),
                project.config.base_url.clone(),
                project.config.token.clone(),
            ),
        },
        None => (
            project.config.model.clone(),
            project.config.base_url.clone(),
            project.config.token.clone(),
        ),
    };
    validate_resolved_custom_fields(&project.config.custom_cli, &model, &base_url)
}

fn validate_resolved_custom_fields(
    custom_cli: &str,
    model: &str,
    base_url: &str,
) -> Result<(), String> {
    if base_url.trim().is_empty() {
        return Err("请先配置 API Base URL".to_string());
    }
    if custom_cli == "codex" && model.trim().is_empty() {
        return Err("Codex 自定义服务还需要配置模型名称".to_string());
    }
    validate_model_base_url(base_url)?;
    Ok(())
}

#[cfg(test)]
mod custom_model_compatibility_tests {
    use super::{
        probe_model_endpoint, protocol_probe_succeeded, validate_model_base_url,
        validate_model_endpoints, validate_resolved_custom_fields,
    };
    use crate::models::ModelApiFormat;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    fn mock_protocol_server(
        expected_probe_path: &'static str,
        expected_models_path: &'static str,
    ) -> (String, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = std::thread::spawn(move || {
            for (index, expected_path) in [expected_probe_path, expected_models_path]
                .into_iter()
                .enumerate()
            {
                let (mut stream, _) = listener.accept().unwrap();
                let mut request = [0_u8; 4096];
                let length = stream.read(&mut request).unwrap();
                let request = String::from_utf8_lossy(&request[..length]);
                let method = if index == 0 { "POST" } else { "GET" };
                assert!(
                    request.starts_with(&format!("{} {} HTTP/", method, expected_path)),
                    "unexpected request: {}",
                    request.lines().next().unwrap_or_default()
                );
                if index == 0 {
                    assert!(request.contains("\"model\":\"probe-model\""));
                }
                let status = if index == 0 {
                    "200 OK"
                } else {
                    "404 Not Found"
                };
                write!(
                    stream,
                    "HTTP/1.1 {}\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}",
                    status
                )
                .unwrap();
            }
        });
        (format!("http://{}", address), handle)
    }

    #[test]
    fn legacy_claude_config_can_keep_an_empty_model() {
        assert!(validate_resolved_custom_fields("claude", "", "https://claude.example").is_ok());
    }

    #[test]
    fn codex_custom_provider_requires_a_model() {
        assert!(validate_resolved_custom_fields("codex", "", "https://api.example/v1").is_err());
        assert!(
            validate_resolved_custom_fields("codex", "gpt-custom", "https://api.example/v1")
                .is_ok()
        );
    }

    #[test]
    fn model_base_url_validation_only_checks_url_shape() {
        assert!(validate_model_base_url("https://open.bigmodel.cn/api/anthropic").is_ok());
        assert!(validate_model_base_url("https://api.example/v1/chat/completions").is_ok());
        assert!(validate_model_base_url("https://api.example/v1/responses").is_ok());
        assert!(validate_model_base_url("not-a-url").is_err());
    }

    #[test]
    fn protocol_probe_only_accepts_successful_real_requests() {
        assert!(protocol_probe_succeeded(200));
        assert!(protocol_probe_succeeded(204));
        assert!(!protocol_probe_succeeded(400));
        assert!(!protocol_probe_succeeded(401));
        assert!(!protocol_probe_succeeded(422));
        assert!(!protocol_probe_succeeded(501));
    }

    #[test]
    fn shared_model_requires_one_url_and_a_model_only_for_codex() {
        assert!(validate_model_endpoints("", "", "").is_err());
        assert!(validate_model_endpoints("", "https://claude.example", "").is_ok());
        assert!(validate_model_endpoints("", "", "https://codex.example/v1").is_err());
        assert!(validate_model_endpoints(
            "shared-model",
            "https://claude.example",
            "https://codex.example/v1"
        )
        .is_ok());
    }

    #[tokio::test]
    async fn protocol_probes_hit_the_real_messages_and_responses_routes() {
        let (claude_url, claude_server) =
            mock_protocol_server("/v1/messages", "/v1/models");
        let claude = probe_model_endpoint(
            claude_url,
            String::new(),
            "probe-model".to_string(),
            ModelApiFormat::AnthropicMessages,
        )
        .await
        .unwrap();
        assert!(claude.ok);
        claude_server.join().unwrap();

        let (codex_url, codex_server) = mock_protocol_server("/responses", "/models");
        let codex = probe_model_endpoint(
            codex_url,
            String::new(),
            "probe-model".to_string(),
            ModelApiFormat::OpenaiResponses,
        )
        .await
        .unwrap();
        assert!(codex.ok);
        codex_server.join().unwrap();
    }
}

// ============ Diagnostics Commands ============

#[tauri::command]
pub fn get_diagnostics_status() -> crate::services::diagnostics::DiagnosticsStatus {
    crate::services::diagnostics::status()
}

#[tauri::command]
pub fn set_diagnostics_auto_report(enabled: bool) -> Result<(), String> {
    crate::services::diagnostics::set_auto_report_enabled(enabled)
}

#[tauri::command]
pub fn open_diagnostics_folder() -> Result<(), String> {
    let path = crate::services::diagnostics::diagnostics_dir();
    std::fs::create_dir_all(&path).map_err(|error| error.to_string())?;
    tauri_plugin_opener::open_path(path, None::<&str>).map_err(|error| error.to_string())
}

#[tauri::command]
pub fn reset_webview_compatibility_and_restart(app: tauri::AppHandle) -> Result<(), String> {
    crate::services::diagnostics::reset_compatibility()?;
    app.restart()
}

#[tauri::command]
pub async fn submit_diagnostics(note: Option<String>) -> Result<String, String> {
    tokio::task::spawn_blocking(move || {
        crate::services::diagnostics::submit_manual(env!("CARGO_PKG_VERSION"), note)
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
pub fn record_frontend_error(message: String) {
    crate::services::diagnostics::record_frontend_error(&message);
}

// ============ Portable Mode Commands ============

/// Detect whether the app is running in portable mode.
/// Portable mode is indicated by a `.portable` marker file next to the executable.
#[tauri::command]
pub fn is_portable_mode() -> bool {
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            return dir.join(".portable").exists();
        }
    }
    false
}

/// Get the download URL for the latest portable release.
#[tauri::command]
pub fn get_portable_download_url() -> String {
    "https://github.com/Earthling18/claude-code-launcher/releases/latest".to_string()
}

/// Download a file from URL to temp directory and launch it.
/// Used for downloading and running installer from a specific GitHub release.
#[tauri::command]
pub async fn download_and_run_installer(url: String, filename: String) -> Result<(), String> {
    use std::io::Write;

    let result = tokio::task::spawn_blocking(move || -> Result<(), String> {
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(300))
            .build()
            .map_err(|e| format!("Failed to create HTTP client: {}", e))?;

        let mut resp = client
            .get(&url)
            .header("User-Agent", "CCLauncher")
            .send()
            .map_err(|e| format!("Download failed: {}", e))?;

        if !resp.status().is_success() {
            return Err(format!("Download returned HTTP {}", resp.status()));
        }

        let temp_dir = std::env::temp_dir().join("cc-launcher-update");
        std::fs::create_dir_all(&temp_dir)
            .map_err(|e| format!("Failed to create temp dir: {}", e))?;

        let file_path = temp_dir.join(&filename);
        let mut file = std::fs::File::create(&file_path)
            .map_err(|e| format!("Failed to create file: {}", e))?;

        resp.copy_to(&mut file)
            .map_err(|e| format!("Failed to write file: {}", e))?;
        file.flush()
            .map_err(|e| format!("Failed to flush file: {}", e))?;
        drop(file);

        log::info!("Downloaded installer to: {}", file_path.display());

        // Launch the installer
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            std::process::Command::new(&file_path)
                .creation_flags(0x08000000)
                .spawn()
                .map_err(|e| format!("Failed to launch installer: {}", e))?;
        }
        #[cfg(not(windows))]
        {
            std::process::Command::new("open")
                .arg(&file_path)
                .spawn()
                .map_err(|e| format!("Failed to open installer: {}", e))?;
        }

        Ok(())
    })
    .await
    .map_err(|e| format!("Task error: {}", e))?;

    result
}
