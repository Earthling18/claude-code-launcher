use crate::services::*;
use crate::services::bridge_manager::BridgeStatus;
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
            // Claude native mode: proxy only
            if !project.config.proxy.is_empty() {
                config.insert("HTTP_PROXY".to_string(), project.config.proxy.clone());
                config.insert("HTTPS_PROXY".to_string(), project.config.proxy.clone());
            }
        }
        "codex" => {
            // Codex native mode: OPENAI_API_KEY, launch codex CLI
            config.insert("CLI_COMMAND".to_string(), "codex".to_string());
            if !project.config.codex_api_key.is_empty() {
                config.insert("OPENAI_API_KEY".to_string(), project.config.codex_api_key.clone());
            }
        }
        "custom" => {
            if project.config.custom_cli == "codex" {
                // Custom mode with Codex CLI
                let mut cli_cmd = "codex".to_string();
                if !project.config.model.is_empty() {
                    cli_cmd.push_str(&format!(" --model {}", project.config.model));
                }
                if !project.config.base_url.is_empty() {
                    cli_cmd.push_str(&format!(" --provider {}", project.config.base_url));
                }
                config.insert("CLI_COMMAND".to_string(), cli_cmd);
                // For custom+codex, use token field as OPENAI_API_KEY
                if !project.config.token.is_empty() {
                    config.insert("OPENAI_API_KEY".to_string(), project.config.token.clone());
                }
            } else {
                // Custom mode with Claude CLI (default)
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
        _ => {
            // remote or unknown — no CLI config needed
        }
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

#[tauri::command]
pub fn get_onboarding_status() -> Result<bool, String> {
    ConfigStorage::get_onboarding_status()
}

#[tauri::command]
pub fn set_onboarding_completed() -> Result<(), String> {
    ConfigStorage::set_onboarding_completed()
}

// ============ Bridge Management Commands ============

#[tauri::command]
pub fn start_bridge(id: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    let config = if id == "__remote__" {
        ConfigStorage::load_remote_config()?
    } else {
        let project = ConfigStorage::get_project(&id)?;
        if project.config.mode != "remote" {
            return Err("Project is not in remote bridge mode".to_string());
        }
        project.config
    };

    // Get resource dir
    let resource_dir = app_handle
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to get resource dir: {}", e))?;
    let resource_dir_str = resource_dir.to_string_lossy().to_string();

    BridgeManager::start_bridge(&id, &config, &resource_dir_str)
}

#[tauri::command]
pub fn stop_bridge(id: String) -> Result<(), String> {
    BridgeManager::stop_bridge(&id)
}

#[tauri::command]
pub fn get_bridge_status(id: String) -> BridgeStatus {
    BridgeManager::get_status(&id)
}

#[tauri::command]
pub fn get_bridge_logs(id: String, max_lines: Option<usize>) -> Vec<String> {
    BridgeManager::get_logs(&id, max_lines.unwrap_or(200))
}

#[tauri::command]
pub fn restart_bridge(id: String, app_handle: tauri::AppHandle) -> Result<(), String> {
    BridgeManager::stop_bridge(&id)?;

    let config = if id == "__remote__" {
        ConfigStorage::load_remote_config()?
    } else {
        let project = ConfigStorage::get_project(&id)?;
        if project.config.mode != "remote" {
            return Err("Project is not in remote bridge mode".to_string());
        }
        project.config
    };

    let resource_dir = app_handle
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to get resource dir: {}", e))?;
    let resource_dir_str = resource_dir.to_string_lossy().to_string();

    BridgeManager::start_bridge(&id, &config, &resource_dir_str)
}

#[tauri::command]
pub fn check_bridge_deps() -> Result<(), String> {
    BridgeManager::check_deps()
}

#[tauri::command]
pub fn prepare_bridge_env(app_handle: tauri::AppHandle) -> Result<(), String> {
    let resource_dir = app_handle
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to get resource dir: {}", e))?;
    let resource_dir_str = resource_dir.to_string_lossy().to_string();

    BridgeManager::prepare_env(&resource_dir_str)?;
    Ok(())
}

// ============ Agent Config Commands ============

#[tauri::command]
pub fn open_agent_config_file(name: String) -> Result<(), String> {
    let agent_dir = BridgeManager::get_agent_data_dir();
    let path = match name.as_str() {
        "env" => agent_dir.join(".env"),
        "mcp" => agent_dir.join(".mcp.json"),
        "soul" => agent_dir.join("app").join("soul.md"),
        "system_prompt" => agent_dir.join("app").join("system_prompt.md"),
        "allowed_tools" => agent_dir.join("allowed_tools.txt"),
        "claude_md" => agent_dir.join("CLAUDE.md"),
        _ => return Err(format!("Unknown config: {}", name)),
    };
    BridgeManager::open_path_in_system(&path)
}

#[tauri::command]
pub fn open_agent_config_folder(name: String) -> Result<(), String> {
    let agent_dir = BridgeManager::get_agent_data_dir();
    let path = match name.as_str() {
        "skills" => agent_dir.join(".claude").join("skills"),
        "workspace" => agent_dir.join("workspace"),
        "logs" => agent_dir.join("logs"),
        "root" => agent_dir,
        _ => return Err(format!("Unknown folder: {}", name)),
    };
    BridgeManager::open_path_in_system(&path)
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

// ============ Bridge Admin API Commands ============

#[derive(serde::Deserialize)]
pub struct BridgeAdminConfig {
    pub url: String,
    pub user: String,
    pub pass: String,
    pub sendmsg_api_url: String,
    pub sendmsg_auth_key: String,
    pub sendmsg_dep_user_id: String,
    pub cos_api_base: String,
}

pub fn bridge_admin_config() -> BridgeAdminConfig {
    serde_json::from_str(include_str!("../../resources/bridge/bridge_admin.json"))
        .expect("Invalid bridge_admin.json")
}

#[tauri::command]
pub fn get_hostname() -> String {
    // Try reading persisted client_id first (matches Python bridge client behavior)
    if let Some(home) = dirs::home_dir() {
        let id_file = home.join(".agent-bridge").join("client_id");
        if let Ok(id) = std::fs::read_to_string(&id_file) {
            let id = id.trim().to_string();
            if !id.is_empty() {
                return id;
            }
        }
    }
    // Fallback to COMPUTERNAME (Windows) or HOSTNAME
    std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_else(|_| "unknown".to_string())
}

#[tauri::command]
pub fn get_username() -> String {
    std::env::var("USERNAME")
        .or_else(|_| std::env::var("USER"))
        .unwrap_or_else(|_| "unknown".to_string())
        .to_lowercase()
}

#[tauri::command]
pub async fn bridge_get_or_create_key(username: String) -> Result<String, String> {
    let cfg = bridge_admin_config();
    let client = reqwest::Client::builder()
        .no_proxy()
        .build()
        .map_err(|e| format!("HTTP 客户端初始化失败: {}", e))?;

    // 1. Login to get admin token
    let login_res = client
        .post(format!("{}/api/login", cfg.url))
        .json(&serde_json::json!({
            "username": cfg.user,
            "password": cfg.pass
        }))
        .send()
        .await
        .map_err(|e| format!("连接管理后台失败: {}", e))?;

    if !login_res.status().is_success() {
        return Err("管理后台登录失败".to_string());
    }

    // Extract admin_token from Set-Cookie header
    let token = login_res
        .headers()
        .get_all("set-cookie")
        .iter()
        .find_map(|v| {
            let s = v.to_str().ok()?;
            for part in s.split(';') {
                let part = part.trim();
                if let Some(val) = part.strip_prefix("admin_token=") {
                    return Some(val.to_string());
                }
            }
            None
        })
        .ok_or_else(|| "登录成功但未获取到认证令牌".to_string())?;

    let cookie_header = format!("admin_token={}", token);

    // 2. Try to get existing user
    let get_res = client
        .get(format!("{}/api/admin/users/{}", cfg.url, username))
        .header("Cookie", &cookie_header)
        .send()
        .await
        .map_err(|e| format!("查询用户失败: {}", e))?;

    if get_res.status().is_success() {
        let data: serde_json::Value = get_res
            .json()
            .await
            .map_err(|e| format!("解析响应失败: {}", e))?;
        if let Some(key) = data["user"]["api_key"].as_str() {
            if !key.is_empty() {
                return Ok(key.to_string());
            }
        }
    }

    // 3. Create new user
    let create_res = client
        .post(format!("{}/api/admin/users", cfg.url))
        .header("Cookie", &cookie_header)
        .json(&serde_json::json!({
            "user_id": username,
            "name": username,
            "max_clients": 5
        }))
        .send()
        .await
        .map_err(|e| format!("创建用户失败: {}", e))?;

    if !create_res.status().is_success() {
        let body = create_res.text().await.unwrap_or_default();
        return Err(format!("创建用户失败: {}", body));
    }

    let data: serde_json::Value = create_res
        .json()
        .await
        .map_err(|e| format!("解析响应失败: {}", e))?;
    data["user"]["api_key"]
        .as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| "创建成功但未获取到 API Key".to_string())
}

// ============ Remote Config Commands ============

#[tauri::command]
pub fn load_remote_config() -> Result<ProjectConfig, String> {
    ConfigStorage::load_remote_config()
}

#[tauri::command]
pub fn save_remote_config(config: ProjectConfig) -> Result<(), String> {
    ConfigStorage::save_remote_config(&config)
}

#[tauri::command]
pub fn start_remote_bridge(app_handle: tauri::AppHandle) -> Result<(), String> {
    let config = ConfigStorage::load_remote_config()?;
    if config.bridge_bind_key.is_empty() {
        return Err("请先配置 Bind Key".to_string());
    }

    let resource_dir = app_handle
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to get resource dir: {}", e))?;
    let resource_dir_str = resource_dir.to_string_lossy().to_string();

    BridgeManager::start_bridge("__remote__", &config, &resource_dir_str)
}
