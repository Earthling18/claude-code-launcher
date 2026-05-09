use crate::services::*;
use crate::services::cc_config_checker::{ConfigScanResult, ProjectInfo, CleanTarget};
use crate::models::{
    Project, ProjectConfig, CreateProjectInput, UpdateProjectInput, ProjectOrderItem, PinnedOrderItem,
    GlobalPresets, ModelPreset, ProxyPreset,
};
use std::collections::HashMap;

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
pub fn launch_claude_code(config: HashMap<String, String>) -> Result<(), String> {
    Launcher::launch_with_config(config)
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
pub fn create_project(name: String, working_directory: String, config: ProjectConfig) -> Result<Project, String> {
    let input = CreateProjectInput {
        name,
        working_directory,
        config,
    };
    ConfigStorage::create_project(input)
}

#[tauri::command]
pub fn update_project(id: String, name: Option<String>, working_directory: Option<String>, config: Option<ProjectConfig>, is_pinned: Option<bool>) -> Result<Project, String> {
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
pub fn launch_project(id: String) -> Result<(), String> {
    let project = ConfigStorage::get_project(&id)?;
    let config = build_config_map(&project);

    // Launch with working directory
    Launcher::launch_with_config_and_dir(config, Some(project.working_directory.clone()))?;

    // Update last launched timestamp
    let _ = ConfigStorage::update_project_launched(&id);

    Ok(())
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
    Ok(Launcher::generate_powershell_command_with_dir(&config, Some(project.working_directory)))
}

#[tauri::command]
pub fn generate_project_cmd_command(id: String) -> Result<String, String> {
    let project = ConfigStorage::get_project(&id)?;
    let config = build_config_map(&project);
    Ok(Launcher::generate_cmd_command_with_dir(&config, Some(project.working_directory)))
}

#[tauri::command]
pub fn generate_project_bash_command(id: String) -> Result<String, String> {
    let project = ConfigStorage::get_project(&id)?;
    let config = build_config_map(&project);
    Ok(Launcher::generate_bash_command_with_dir(&config, Some(project.working_directory)))
}

/// Resolve effective proxy URL: preset wins, legacy field is fallback.
fn resolve_proxy(project: &Project, presets: &crate::models::GlobalPresets) -> String {
    if let Some(id) = &project.config.proxy_preset_id {
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
    if let Some(id) = &project.config.model_preset_id {
        if let Some(m) = presets.models.iter().find(|m| &m.id == id) {
            return (m.model.clone(), m.base_url.clone(), m.token.clone());
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
            config.insert("CLI_COMMAND".to_string(), "codex".to_string());
            let proxy = resolve_proxy(project, &presets);
            if !proxy.is_empty() {
                config.insert("HTTP_PROXY".to_string(), proxy.clone());
                config.insert("HTTPS_PROXY".to_string(), proxy);
            }
        }
        "custom" => {
            let (model, base_url, token) = resolve_model(project, &presets);
            if project.config.custom_cli == "codex" {
                let mut cli_cmd = "codex".to_string();
                if !model.is_empty() {
                    cli_cmd.push_str(&format!(" --model {}", model));
                }
                config.insert("CLI_COMMAND".to_string(), cli_cmd);
                if !base_url.is_empty() {
                    config.insert("OPENAI_BASE_URL".to_string(), base_url);
                }
                if !token.is_empty() {
                    config.insert("OPENAI_API_KEY".to_string(), token);
                }
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
pub fn launch_claude_for_login(proxy: Option<String>) -> Result<(), String> {
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
    base_url: String,
    token: String,
) -> Result<ModelPreset, String> {
    PresetsStorage::create_model(name, model, base_url, token)
}

#[tauri::command]
pub fn update_model_preset(
    id: String,
    name: String,
    model: String,
    base_url: String,
    token: String,
) -> Result<ModelPreset, String> {
    PresetsStorage::update_model(&id, name, model, base_url, token)
}

#[tauri::command]
pub fn delete_model_preset(id: String) -> Result<(), String> {
    PresetsStorage::delete_model(&id)
}

#[tauri::command]
pub fn count_model_preset_refs(id: String) -> usize {
    PresetsStorage::count_model_refs(&id)
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
    if project.config.mode != "custom" {
        return Ok(());
    }
    let presets = PresetsStorage::load();
    let (model, base_url, _token) = match &project.config.model_preset_id {
        Some(pid) => match presets.models.iter().find(|m| &m.id == pid) {
            Some(m) => (m.model.clone(), m.base_url.clone(), m.token.clone()),
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
    if model.is_empty() && base_url.is_empty() {
        return Err("请先配置模型".to_string());
    }
    Ok(())
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
    "https://github.com/erthman18/claude-code-launcher/releases/latest".to_string()
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

