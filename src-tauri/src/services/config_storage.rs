use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use base64::{Engine as _, engine::general_purpose};
use crate::models::{Project, ProjectConfig, CreateProjectInput, UpdateProjectInput, ProjectOrderItem, PinnedOrderItem};

fn default_skip_permissions() -> bool {
    true
}

/// Legacy v1 config format (for migration)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub mode: String,
    pub proxy: String,
    pub model: String,
    pub base_url: String,
    pub token: String,
    #[serde(default = "default_skip_permissions")]
    pub skip_permissions: bool,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            mode: "claude".to_string(),
            proxy: String::new(),
            model: "qwen3-coder-480b-a35b".to_string(),
            base_url: "http://litellm.uattest.weoa.com".to_string(),
            token: String::new(),
            skip_permissions: true,
        }
    }
}

/// V2 config format with multi-project support
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfigV2 {
    pub version: u32,
    pub projects: Vec<Project>,
    #[serde(default)]
    pub has_seen_onboarding: bool,
}

impl Default for AppConfigV2 {
    fn default() -> Self {
        Self {
            version: 2,
            projects: vec![Project::default_project()],
            has_seen_onboarding: false,
        }
    }
}

/// Raw config for detecting version
#[derive(Debug, Clone, Serialize, Deserialize)]
struct RawConfig {
    #[serde(default)]
    version: Option<u32>,
}

pub struct ConfigStorage;

impl ConfigStorage {
    fn get_config_path() -> Result<PathBuf, String> {
        let base = dirs::config_dir()
            .ok_or("无法获取配置目录")?;
        let new_dir = base.join("CCLauncher");
        let mobot_dir = base.join("MobotLauncher");
        let legacy_dir = base.join("ClaudeCodeLauncher");

        // Three-way migration: pick the most-recent old name and rename to new.
        if !new_dir.exists() {
            let src = if mobot_dir.exists() {
                Some(mobot_dir.clone())
            } else if legacy_dir.exists() {
                Some(legacy_dir.clone())
            } else {
                None
            };
            if let Some(s) = src {
                log::info!(
                    "Migrating config directory: {} -> {}",
                    s.display(),
                    new_dir.display()
                );
                if let Err(e) = fs::rename(&s, &new_dir) {
                    log::error!("Config migration failed (will use old path): {}", e);
                }
            }
        }

        let config_dir = if new_dir.exists() {
            new_dir
        } else if mobot_dir.exists() {
            mobot_dir
        } else if legacy_dir.exists() {
            legacy_dir
        } else {
            new_dir
        };

        if !config_dir.exists() {
            fs::create_dir_all(&config_dir)
                .map_err(|e| format!("无法创建配置目录: {}", e))?;
        }

        Ok(config_dir.join("config.json"))
    }

    /// Migrate v1 config to v2 format
    fn migrate_v1_to_v2(v1_config: AppConfig) -> AppConfigV2 {
        let home_dir = dirs::home_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "~".to_string());

        let project_config = ProjectConfig {
            mode: v1_config.mode,
            proxy: v1_config.proxy,
            model: v1_config.model,
            base_url: v1_config.base_url,
            token: v1_config.token,
            skip_permissions: v1_config.skip_permissions,
            ..Default::default()
        };

        let default_project = Project::new(
            "默认项目".to_string(),
            home_dir,
            project_config,
            true,
        );

        AppConfigV2 {
            version: 2,
            projects: vec![default_project],
            has_seen_onboarding: false,
        }
    }

    /// Encode token in project config for storage
    fn encode_project_token(project: &mut Project) {
        if !project.config.token.is_empty() {
            project.config.token = general_purpose::STANDARD.encode(&project.config.token);
        }
        if !project.config.codex_api_key.is_empty() {
            project.config.codex_api_key = general_purpose::STANDARD.encode(&project.config.codex_api_key);
        }
    }

    /// Decode token in project config after loading
    fn decode_project_token(project: &mut Project) {
        if !project.config.token.is_empty() {
            if let Ok(decoded) = general_purpose::STANDARD.decode(&project.config.token) {
                if let Ok(token_str) = String::from_utf8(decoded) {
                    project.config.token = token_str;
                }
            }
        }
        if !project.config.codex_api_key.is_empty() {
            if let Ok(decoded) = general_purpose::STANDARD.decode(&project.config.codex_api_key) {
                if let Ok(key_str) = String::from_utf8(decoded) {
                    project.config.codex_api_key = key_str;
                }
            }
        }
    }

    /// Load v2 config, migrating from v1 if necessary
    pub fn load_config_v2() -> Result<AppConfigV2, String> {
        let config_path = Self::get_config_path()?;

        if !config_path.exists() {
            return Ok(AppConfigV2::default());
        }

        let content = fs::read_to_string(&config_path)
            .map_err(|e| format!("无法读取配置文件: {}", e))?;

        // Detect version
        let raw: RawConfig = serde_json::from_str(&content)
            .map_err(|e| format!("无法解析配置文件: {}", e))?;

        if raw.version == Some(2) {
            // Load v2 config directly
            let mut config: AppConfigV2 = serde_json::from_str(&content)
                .map_err(|e| format!("无法解析v2配置: {}", e))?;

            // Decode tokens + coerce legacy mode='remote' → 'claude'
            for project in &mut config.projects {
                Self::decode_project_token(project);
                project.config.normalize_legacy_mode();
            }

            Ok(config)
        } else {
            // Migrate from v1
            let mut v1_config: AppConfig = serde_json::from_str(&content)
                .map_err(|e| format!("无法解析v1配置: {}", e))?;

            // Decode v1 token
            if !v1_config.token.is_empty() {
                if let Ok(decoded) = general_purpose::STANDARD.decode(&v1_config.token) {
                    if let Ok(token_str) = String::from_utf8(decoded) {
                        v1_config.token = token_str;
                    }
                }
            }

            let config = Self::migrate_v1_to_v2(v1_config);

            // Save migrated config
            Self::save_config_v2(&config)?;

            Ok(config)
        }
    }

    /// Save v2 config
    pub fn save_config_v2(config: &AppConfigV2) -> Result<(), String> {
        let config_path = Self::get_config_path()?;

        // Create a copy with encoded tokens
        let mut config_to_save = config.clone();
        for project in &mut config_to_save.projects {
            Self::encode_project_token(project);
        }

        let json_string = serde_json::to_string_pretty(&config_to_save)
            .map_err(|e| format!("无法序列化配置: {}", e))?;

        fs::write(&config_path, json_string)
            .map_err(|e| format!("无法写入配置文件: {}", e))?;

        Ok(())
    }

    /// Get all projects
    pub fn get_projects() -> Result<Vec<Project>, String> {
        let config = Self::load_config_v2()?;
        Ok(config.projects)
    }

    /// Get a single project by ID
    pub fn get_project(id: &str) -> Result<Project, String> {
        let config = Self::load_config_v2()?;
        config.projects
            .into_iter()
            .find(|p| p.id == id)
            .ok_or_else(|| format!("项目不存在: {}", id))
    }

    /// Create a new project
    pub fn create_project(input: CreateProjectInput) -> Result<Project, String> {
        let mut config = Self::load_config_v2()?;

        let max_order = config.projects
            .iter()
            .filter(|p| !p.is_pinned)
            .map(|p| p.sort_order)
            .max()
            .unwrap_or(0);

        let project = Project::new_with_sort_order(
            input.name,
            input.working_directory,
            input.config,
            false,
            max_order + 1,
        );

        config.projects.push(project.clone());
        Self::save_config_v2(&config)?;

        Ok(project)
    }

    /// Update an existing project
    pub fn update_project(id: &str, updates: UpdateProjectInput) -> Result<Project, String> {
        let mut config = Self::load_config_v2()?;

        let max_order = config.projects
            .iter()
            .filter(|p| !p.is_pinned && p.id != id)
            .map(|p| p.sort_order)
            .max()
            .unwrap_or(0);

        let project = config.projects
            .iter_mut()
            .find(|p| p.id == id)
            .ok_or_else(|| format!("项目不存在: {}", id))?;

        if let Some(name) = updates.name {
            project.name = name;
        }
        if let Some(working_directory) = updates.working_directory {
            project.working_directory = working_directory;
        }
        if let Some(new_config) = updates.config {
            project.config = new_config;
        }
        if let Some(is_pinned) = updates.is_pinned {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs();

            if is_pinned && !project.is_pinned {
                project.is_pinned = true;
                project.pinned_at = Some(now);
            } else if !is_pinned && project.is_pinned {
                project.is_pinned = false;
                project.pinned_at = None;
                project.sort_order = max_order + 1;
            }
        }

        project.updated_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        let updated_project = project.clone();
        Self::save_config_v2(&config)?;

        Ok(updated_project)
    }

    /// Delete a project (cannot delete default project)
    pub fn delete_project(id: &str) -> Result<(), String> {
        let mut config = Self::load_config_v2()?;

        let project = config.projects
            .iter()
            .find(|p| p.id == id)
            .ok_or_else(|| format!("项目不存在: {}", id))?;

        if project.is_default {
            return Err("不能删除默认项目".to_string());
        }

        config.projects.retain(|p| p.id != id);
        Self::save_config_v2(&config)?;

        Ok(())
    }

    /// Update project's last launched timestamp
    pub fn update_project_launched(id: &str) -> Result<(), String> {
        let mut config = Self::load_config_v2()?;

        if let Some(project) = config.projects.iter_mut().find(|p| p.id == id) {
            project.last_launched_at = Some(
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs()
            );
            Self::save_config_v2(&config)?;
        }

        Ok(())
    }

    /// Update sort order for non-pinned projects (batch)
    pub fn update_projects_order(orders: Vec<ProjectOrderItem>) -> Result<(), String> {
        let mut config = Self::load_config_v2()?;

        for order_item in orders {
            if let Some(project) = config.projects.iter_mut().find(|p| p.id == order_item.id) {
                if !project.is_pinned && !project.is_default {
                    project.sort_order = order_item.sort_order;
                }
            }
        }

        Self::save_config_v2(&config)?;
        Ok(())
    }

    /// Update pinned_at for pinned projects (batch)
    pub fn update_pinned_order(orders: Vec<PinnedOrderItem>) -> Result<(), String> {
        let mut config = Self::load_config_v2()?;

        for order_item in orders {
            if let Some(project) = config.projects.iter_mut().find(|p| p.id == order_item.id) {
                if project.is_pinned {
                    project.pinned_at = Some(order_item.pinned_at);
                }
            }
        }

        Self::save_config_v2(&config)?;
        Ok(())
    }

    /// Toggle project pinned status
    pub fn toggle_project_pinned(id: &str, is_pinned: bool) -> Result<Project, String> {
        let updates = UpdateProjectInput {
            name: None,
            working_directory: None,
            config: None,
            is_pinned: Some(is_pinned),
        };
        Self::update_project(id, updates)
    }

    /// Get onboarding status
    pub fn get_onboarding_status() -> Result<bool, String> {
        let config = Self::load_config_v2()?;
        Ok(config.has_seen_onboarding)
    }

    /// Set onboarding as completed
    pub fn set_onboarding_completed() -> Result<(), String> {
        let mut config = Self::load_config_v2()?;
        config.has_seen_onboarding = true;
        Self::save_config_v2(&config)
    }

    // ============ Legacy v1 API for backwards compatibility ============

    pub fn save_config(config: &AppConfig) -> Result<(), String> {
        let mut v2_config = Self::load_config_v2().unwrap_or_default();

        if let Some(default_project) = v2_config.projects.iter_mut().find(|p| p.is_default) {
            default_project.config = ProjectConfig {
                mode: config.mode.clone(),
                proxy: config.proxy.clone(),
                model: config.model.clone(),
                base_url: config.base_url.clone(),
                token: config.token.clone(),
                skip_permissions: config.skip_permissions,
                ..Default::default()
            };
            default_project.updated_at = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs();
        }

        Self::save_config_v2(&v2_config)
    }

    pub fn load_config() -> Result<AppConfig, String> {
        let config = Self::load_config_v2()?;

        let default_project = config.projects
            .iter()
            .find(|p| p.is_default)
            .cloned()
            .unwrap_or_else(Project::default_project);

        Ok(AppConfig {
            mode: default_project.config.mode,
            proxy: default_project.config.proxy,
            model: default_project.config.model,
            base_url: default_project.config.base_url,
            token: default_project.config.token,
            skip_permissions: default_project.config.skip_permissions,
        })
    }
}
