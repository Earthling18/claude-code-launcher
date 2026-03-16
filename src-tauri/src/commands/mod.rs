use crate::services::*;
use crate::services::bridge_manager::{InstallStatus, HealthStatus, MobotServiceStatus};
use crate::services::cc_config_checker::{ConfigScanResult, ProjectInfo, CleanTarget};
use crate::models::{Project, ProjectConfig, CreateProjectInput, UpdateProjectInput, ProjectOrderItem, PinnedOrderItem};
use std::collections::HashMap;
use tauri::Manager;

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

fn build_config_map(project: &Project) -> HashMap<String, String> {
    let mut config: HashMap<String, String> = HashMap::new();

    match project.config.mode.as_str() {
        "claude" => {
            if !project.config.proxy.is_empty() {
                config.insert("HTTP_PROXY".to_string(), project.config.proxy.clone());
                config.insert("HTTPS_PROXY".to_string(), project.config.proxy.clone());
            }
        }
        "codex" => {
            config.insert("CLI_COMMAND".to_string(), "codex".to_string());
            if !project.config.codex_api_key.is_empty() {
                config.insert("HTTP_PROXY".to_string(), project.config.codex_api_key.clone());
                config.insert("HTTPS_PROXY".to_string(), project.config.codex_api_key.clone());
            }
        }
        "custom" => {
            if project.config.custom_cli == "codex" {
                let mut cli_cmd = "codex".to_string();
                if !project.config.model.is_empty() {
                    cli_cmd.push_str(&format!(" --model {}", project.config.model));
                }
                config.insert("CLI_COMMAND".to_string(), cli_cmd);
                if !project.config.base_url.is_empty() {
                    config.insert("OPENAI_BASE_URL".to_string(), project.config.base_url.clone());
                }
                if !project.config.token.is_empty() {
                    config.insert("OPENAI_API_KEY".to_string(), project.config.token.clone());
                }
            } else {
                if !project.config.model.is_empty() {
                    config.insert("ANTHROPIC_MODEL".to_string(), project.config.model.clone());
                }
                if !project.config.base_url.is_empty() {
                    config.insert("ANTHROPIC_BASE_URL".to_string(), project.config.base_url.clone());
                }
                if !project.config.token.is_empty() {
                    config.insert("ANTHROPIC_AUTH_TOKEN".to_string(), project.config.token.clone());
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

// ============ Mobot Bridge Management Commands ============

#[tauri::command]
pub async fn detect_mobot_installation(app_handle: tauri::AppHandle) -> InstallStatus {
    let status = tokio::task::spawn_blocking(BridgeManager::detect_installation)
        .await
        .unwrap_or(InstallStatus::NotInstalled);

    // If installed, ensure bundled resources (e.g. mingit/) exist in the bridge dir.
    // This must run here (not just in start_service) because the service may already
    // be running, in which case start_service is never called.
    if !matches!(status, InstallStatus::NotInstalled) {
        let bridge_dir = BridgeManager::get_mobot_dir();
        BridgeManager::ensure_bundled_resources(&bridge_dir);
    }

    // If installed, compare installed version with bundled version
    // to force re-install when app is upgraded (e.g. master -> mobot branch)
    if !matches!(status, InstallStatus::NotInstalled) {
        if let Ok(resource_dir) = app_handle.path().resource_dir() {
            let resource_dir_str = resource_dir.to_string_lossy();
            let resource_dir_clean = resource_dir_str.strip_prefix(r"\\?\").unwrap_or(&resource_dir_str);
            if let Ok(src) = BridgeManager::find_bridge_source_pub(resource_dir_clean) {
                let bundled_version = std::fs::read_to_string(src.join("VERSION"))
                    .unwrap_or_default().trim().to_string();
                let installed_version = std::fs::read_to_string(
                    BridgeManager::get_mobot_dir().join(".mobot_version")
                ).unwrap_or_default().trim().to_string();

                if !bundled_version.is_empty() && bundled_version != installed_version {
                    log::info!(
                        "Version mismatch: installed={}, bundled={} — forcing re-install",
                        installed_version, bundled_version
                    );
                    return InstallStatus::NotInstalled;
                }
            }
        }
    }

    status
}

#[tauri::command]
pub async fn install_mobot_bridge(app_handle: tauri::AppHandle) -> Result<String, String> {
    let resource_dir = app_handle
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to get resource dir: {}", e))?;
    let resource_dir_str = resource_dir.to_string_lossy().to_string();

    tokio::task::spawn_blocking(move || BridgeManager::install_mobot_bridge(&resource_dir_str))
        .await
        .map_err(|e| format!("Task error: {}", e))?
}

#[tauri::command]
pub async fn check_mobot_deps_installed(bridge_path: String) -> bool {
    BridgeManager::check_deps_installed(&bridge_path)
}

#[tauri::command]
pub async fn detect_python() -> Option<String> {
    tokio::task::spawn_blocking(BridgeManager::detect_python)
        .await
        .unwrap_or(None)
}

#[tauri::command]
pub async fn install_mobot_deps(app_handle: tauri::AppHandle, bridge_path: String, python: String) -> Result<String, String> {
    tokio::task::spawn_blocking(move || BridgeManager::install_dependencies(&bridge_path, &python, Some(&app_handle)))
        .await
        .map_err(|e| format!("Task error: {}", e))?
}

#[tauri::command]
pub async fn start_mobot_service(bridge_path: String, python: String, port: u16) -> Result<u32, String> {
    tokio::task::spawn_blocking(move || BridgeManager::start_service(&bridge_path, &python, port))
        .await
        .map_err(|e| format!("Task error: {}", e))?
}

#[tauri::command]
pub async fn stop_mobot_service() -> Result<(), String> {
    tokio::task::spawn_blocking(BridgeManager::stop_service)
        .await
        .map_err(|e| format!("Task error: {}", e))?
}

#[tauri::command]
pub async fn check_mobot_health(port: u16) -> HealthStatus {
    tokio::task::spawn_blocking(move || BridgeManager::check_health(port))
        .await
        .unwrap_or(HealthStatus { healthy: false, details: "Task error".to_string() })
}

#[tauri::command]
pub async fn get_mobot_status(port: u16) -> MobotServiceStatus {
    tokio::task::spawn_blocking(move || BridgeManager::get_service_status(port))
        .await
        .unwrap_or(MobotServiceStatus {
            installed: false, running: false, pid: None,
            port, install_path: None, healthy: false, started_at: None,
        })
}

#[tauri::command]
pub async fn get_mobot_logs(max_lines: Option<usize>) -> Vec<String> {
    let lines = max_lines.unwrap_or(200);
    tokio::task::spawn_blocking(move || BridgeManager::get_logs(lines))
        .await
        .unwrap_or_default()
}

#[tauri::command]
pub async fn is_mobot_updating() -> bool {
    tokio::task::spawn_blocking(BridgeManager::is_updating)
        .await
        .unwrap_or(false)
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

// ============ Utility Commands ============

#[tauri::command]
pub fn get_hostname() -> String {
    BridgeManager::get_hostname()
}

#[tauri::command]
pub fn get_username() -> String {
    BridgeManager::get_username()
}
