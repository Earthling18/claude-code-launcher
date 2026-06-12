# Mobot Launcher Tauri - API Reference

> **项目版本**: 1.0.4
> **最后更新**: 2026-03-13
> **API 数量**: 67 个 Tauri Commands

---

## 目录

1. [依赖检测 API](#1-依赖检测-api) (8 个)
2. [安装/更新 API](#2-安装更新-api) (8 个)
3. [系统工具 API](#3-系统工具-api) (2 个)
4. [启动器 API](#4-启动器-api) (4 个)
5. [命令生成 API](#5-命令生成-api) (3 个)
6. [设置管理 API](#6-设置管理-api) (3 个)
7. [应用配置 API](#7-应用配置-api) (2 个)
8. [项目管理 API](#8-项目管理-api) (14 个)
9. [引导 API](#9-引导-api) (2 个)
10. [Mobot Bridge 管理 API](#10-mobot-bridge-管理-api) (11 个)
11. [Claude 登录 API](#11-claude-登录-api) (2 个)
12. [CC 配置检查 API](#12-cc-配置检查-api) (7 个)
13. [便携模式 API](#13-便携模式-api) (2 个)
14. [工具 API](#14-工具-api) (2 个)

---

## 类型定义

### DependencyStatus (Rust / TypeScript)

```rust
// src-tauri/src/services/dependency_checker.rs
pub struct DependencyStatus {
    pub installed: bool,
    pub version: Option<String>,
    pub meets_requirement: bool,
    pub latest_version: Option<String>,
    pub update_available: bool,
    pub error: Option<String>,
}
```

```typescript
// src/types.ts
export interface DependencyStatus {
  installed: boolean;
  version: string | null;
  meets_requirement: boolean;
  latest_version: string | null;
  update_available: boolean;
  error: string | null;
}
```

### AppConfig (Rust / TypeScript)

```rust
// src-tauri/src/services/config_storage.rs
pub struct AppConfig {
    pub mode: String,
    pub proxy: String,
    pub model: String,
    pub base_url: String,
    pub token: String,
    pub skip_permissions: bool,
}
```

```typescript
// src/types.ts
export interface AppConfig {
  mode: 'claude' | 'custom';
  proxy: string;
  model: string;
  base_url: string;
  token: string;
  skip_permissions: boolean;
}
```

### Project (Rust / TypeScript)

```rust
// src-tauri/src/models/project.rs
pub struct Project {
    pub id: String,
    pub name: String,
    pub working_directory: String,
    pub config: ProjectConfig,
    pub is_default: bool,
    pub created_at: u64,
    pub updated_at: u64,
    pub last_launched_at: Option<u64>,
    pub is_pinned: bool,
    pub pinned_at: Option<u64>,
    pub sort_order: u32,
}
```

```typescript
// src/types/project.ts
export interface Project {
  id: string;
  name: string;
  working_directory: string;
  config: ProjectConfig;
  is_default: boolean;
  created_at: number;
  updated_at: number;
  last_launched_at?: number;
  is_pinned: boolean;
  pinned_at?: number;
  sort_order: number;
}
```

### ProjectConfig (Rust / TypeScript)

```rust
// src-tauri/src/models/project.rs
pub struct ProjectConfig {
    pub mode: String,                        // "claude", "custom", "codex", or "remote"
    pub proxy: String,                       // HTTP/HTTPS proxy for Claude mode
    pub model: String,                       // Model name for custom mode
    pub base_url: String,                    // API base URL for custom mode
    pub token: String,                       // API token (Base64 encoded in storage)
    pub skip_permissions: bool,              // Skip permissions flag (default: true)
    pub codex_api_key: String,               // Proxy for Codex mode
    pub custom_cli: String,                  // CLI tool for custom mode: "claude" or "codex"
    pub mobot_bridge_path: Option<String>,   // Install path (auto-detected or user-specified)
    pub mobot_bridge_port: u16,              // Service port (default 8000)
}
```

```typescript
// src/types/project.ts
export interface ProjectConfig {
  mode: 'claude' | 'custom' | 'codex' | 'remote';
  proxy: string;
  model: string;
  base_url: string;
  token: string;
  skip_permissions: boolean;
  codex_api_key: string;
  custom_cli: 'claude' | 'codex';
  mobot_bridge_path: string | null;
  mobot_bridge_port: number;
}
```

### InstallStatus (Rust / TypeScript)

```rust
// src-tauri/src/services/bridge_manager.rs
pub enum InstallStatus {
    NotInstalled,
    Installed { path: String },
    Running { path: String, port: u16 },
}
```

```typescript
// src/types/project.ts
export type InstallStatus =
  | 'NotInstalled'
  | { Installed: { path: string } }
  | { Running: { path: string; port: number } };
```

### HealthStatus (Rust / TypeScript)

```rust
// src-tauri/src/services/bridge_manager.rs
pub struct HealthStatus {
    pub healthy: bool,
    pub details: String,
}
```

```typescript
// src/types/project.ts
export interface HealthStatus {
  healthy: boolean;
  details: string;
}
```

### MobotServiceStatus (Rust / TypeScript)

```rust
// src-tauri/src/services/bridge_manager.rs
pub struct MobotServiceStatus {
    pub installed: bool,
    pub running: bool,
    pub pid: Option<u32>,
    pub port: u16,
    pub install_path: Option<String>,
    pub healthy: bool,
    pub started_at: Option<u64>,
}
```

```typescript
// src/types/project.ts
export interface MobotServiceStatus {
  installed: boolean;
  running: boolean;
  pid: number | null;
  port: number;
  install_path: string | null;
  healthy: boolean;
  started_at: number | null;
}
```

### ConfigScanResult / ConfigConflict / BomFileIssue / McpMisplaced / CleanTarget / ProjectInfo

```rust
// src-tauri/src/services/cc_config_checker.rs
pub struct ConfigScanResult {
    pub conflicts: Vec<ConfigConflict>,
    pub bom_files: Vec<BomFileIssue>,
    pub mcp_misplaced: Vec<McpMisplaced>,
}

pub struct ConfigConflict {
    pub source: String,
    pub file_path: Option<String>,
    pub key: String,
    pub value: String,
    pub can_clean: bool,
}

pub struct BomFileIssue {
    pub file_path: String,
}

pub struct McpMisplaced {
    pub file_path: String,
    pub target_path: String,
    pub keys: Vec<String>,
    pub can_fix: bool,
}

pub struct CleanTarget {
    pub file_path: String,
    pub key: String,
}

pub struct ProjectInfo {
    pub name: String,
    pub working_directory: String,
}
```

### ProjectOrderItem / PinnedOrderItem

```rust
// src-tauri/src/models/project.rs
pub struct ProjectOrderItem {
    pub id: String,
    pub sort_order: u32,
}

pub struct PinnedOrderItem {
    pub id: String,
    pub pinned_at: u64,
}
```

### CreateProjectInput / UpdateProjectInput

```rust
// src-tauri/src/models/project.rs
pub struct CreateProjectInput {
    pub name: String,
    pub working_directory: String,
    pub config: ProjectConfig,
}

pub struct UpdateProjectInput {
    pub name: Option<String>,
    pub working_directory: Option<String>,
    pub config: Option<ProjectConfig>,
    pub is_pinned: Option<bool>,
}
```

---

## 1. 依赖检测 API

### 1.1 check_nodejs

**功能**: 检测 Node.js 是否已安装及版本信息（不检查更新）

**Rust 签名**:
```rust
pub async fn check_nodejs() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>`

**前端调用**: `api.checkNodejs()`

---

### 1.2 check_claude

**功能**: 检测 Claude Code CLI 是否已安装及版本信息（不检查更新）

**Rust 签名**:
```rust
pub async fn check_claude() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>`

**前端调用**: `api.checkClaude()`

---

### 1.3 check_gitbash

**功能**: 检测 Git Bash 是否已安装及版本信息（不检查更新）

**Rust 签名**:
```rust
pub async fn check_gitbash() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>`

**前端调用**: `api.checkGitbash()`

---

### 1.4 check_codex

**功能**: 检测 Codex CLI 是否已安装及版本信息（不检查更新）

**Rust 签名**:
```rust
pub async fn check_codex() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>`

**前端调用**: `api.checkCodex()`

---

### 1.5 check_nodejs_with_update

**功能**: 检测 Node.js 安装状态，同时查询最新版本以判断是否有更新

**Rust 签名**:
```rust
pub async fn check_nodejs_with_update() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>` — `update_available` 和 `latest_version` 字段会被填充

**前端调用**: `api.checkNodejsWithUpdate()`

---

### 1.6 check_claude_with_update

**功能**: 检测 Claude Code CLI 安装状态，同时查询最新版本以判断是否有更新

**Rust 签名**:
```rust
pub async fn check_claude_with_update() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>`

**前端调用**: `api.checkClaudeWithUpdate()`

---

### 1.7 check_gitbash_with_update

**功能**: 检测 Git Bash 安装状态，同时查询最新版本以判断是否有更新

**Rust 签名**:
```rust
pub async fn check_gitbash_with_update() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>`

**前端调用**: `api.checkGitbashWithUpdate()`

---

### 1.8 check_codex_with_update

**功能**: 检测 Codex CLI 安装状态，同时查询最新版本以判断是否有更新

**Rust 签名**:
```rust
pub async fn check_codex_with_update() -> Result<DependencyStatus, String>
```

**参数**: 无

**返回值**: `Result<DependencyStatus, String>`

**前端调用**: `api.checkCodexWithUpdate()`

---

## 2. 安装/更新 API

### 2.1 install_nodejs

**功能**: 安装 Node.js（通过系统包管理器或下载安装包）

**Rust 签名**:
```rust
pub async fn install_nodejs() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.installNodejs()`

---

### 2.2 update_nodejs

**功能**: 更新 Node.js 到最新版本

**Rust 签名**:
```rust
pub async fn update_nodejs() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.updateNodejs()`

---

### 2.3 install_claude

**功能**: 安装 Claude Code CLI（通过 npm 全局安装）

**Rust 签名**:
```rust
pub async fn install_claude() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.installClaude()`

---

### 2.4 update_claude

**功能**: 更新 Claude Code CLI 到最新版本

**Rust 签名**:
```rust
pub async fn update_claude() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.updateClaude()`

---

### 2.5 install_gitbash

**功能**: 安装 Git (含 Git Bash)

**Rust 签名**:
```rust
pub async fn install_gitbash() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.installGitbash()`

---

### 2.6 update_gitbash

**功能**: 更新 Git 到最新版本

**Rust 签名**:
```rust
pub async fn update_gitbash() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.updateGitbash()`

---

### 2.7 install_codex

**功能**: 安装 Codex CLI（通过 npm 全局安装）

**Rust 签名**:
```rust
pub async fn install_codex() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.installCodex()`

---

### 2.8 update_codex

**功能**: 更新 Codex CLI 到最新版本

**Rust 签名**:
```rust
pub async fn update_codex() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.updateCodex()`

---

## 3. 系统工具 API

### 3.1 refresh_system_path

**功能**: 刷新系统 PATH 环境变量（仅 Windows 平台生效），用于安装完依赖后让新路径立即可用

**Rust 签名**:
```rust
pub fn refresh_system_path()
```

**参数**: 无

**返回值**: 无（`()`）

**前端调用**: `api.refreshSystemPath()`

---

### 3.2 get_platform

**功能**: 获取当前操作系统平台标识

**Rust 签名**:
```rust
pub fn get_platform() -> String
```

**参数**: 无

**返回值**: `String` — `"windows"` | `"macos"` | `"linux"` | `"unknown"`

**前端调用**: `api.getPlatform()`

---

## 4. 启动器 API

### 4.1 launch_claude_code

**功能**: 使用指定的环境变量配置启动 Claude Code CLI（无项目上下文，在用户主目录启动）

**Rust 签名**:
```rust
pub fn launch_claude_code(config: HashMap<String, String>) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `HashMap<String, String>` | 环境变量键值对，如 `HTTP_PROXY`、`ANTHROPIC_MODEL` 等 |

**返回值**: `Result<(), String>`

**前端调用**: `api.launchClaudeCode(config)`

---

### 4.2 launch_project

**功能**: 根据项目 ID 启动 Claude Code，自动构建环境变量配置并在项目工作目录中启动，同时更新项目的 `last_launched_at` 时间戳

**Rust 签名**:
```rust
pub fn launch_project(id: String) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |

**返回值**: `Result<(), String>`

**前端调用**: `projectApi.launch(id)`

---

### 4.3 launch_claude_for_login

**功能**: 启动 Claude Code CLI 用于登录认证（在用户主目录启动，可选代理）

**Rust 签名**:
```rust
pub fn launch_claude_for_login(proxy: Option<String>) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `proxy` | `Option<String>` | 可选的 HTTP 代理地址 |

**返回值**: `Result<(), String>`

**前端调用**: `claudeLoginApi.launchForLogin(proxy?)`

---

### 4.4 select_directory

**功能**: 打开系统原生目录选择对话框，让用户选择项目工作目录

**Rust 签名**:
```rust
pub async fn select_directory(app_handle: tauri::AppHandle) -> Result<Option<String>, String>
```

**参数**: 无（`app_handle` 由 Tauri 自动注入）

**返回值**: `Result<Option<String>, String>` — 用户选择的目录路径，取消时返回 `None`

**前端调用**: `dialogApi.selectDirectory()`

---

## 5. 命令生成 API

### 5.1 generate_powershell_command

**功能**: 根据环境变量配置生成 PowerShell 启动命令字符串

**Rust 签名**:
```rust
pub fn generate_powershell_command(config: HashMap<String, String>) -> String
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `HashMap<String, String>` | 环境变量键值对 |

**返回值**: `String`

**前端调用**: `api.generatePowershellCommand(config)`

---

### 5.2 generate_cmd_command

**功能**: 根据环境变量配置生成 CMD 启动命令字符串

**Rust 签名**:
```rust
pub fn generate_cmd_command(config: HashMap<String, String>) -> String
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `HashMap<String, String>` | 环境变量键值对 |

**返回值**: `String`

**前端调用**: `api.generateCmdCommand(config)`

---

### 5.3 generate_bash_command

**功能**: 根据环境变量配置生成 Bash 启动命令字符串

**Rust 签名**:
```rust
pub fn generate_bash_command(config: HashMap<String, String>) -> String
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `HashMap<String, String>` | 环境变量键值对 |

**返回值**: `String`

**前端调用**: `api.generateBashCommand(config)`

---

## 6. 设置管理 API

### 6.1 save_to_settings

**功能**: 将环境变量配置保存到 Claude Code 的 `settings.json` 文件中

**Rust 签名**:
```rust
pub fn save_to_settings(config: HashMap<String, String>) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `HashMap<String, String>` | 要保存的环境变量键值对 |

**返回值**: `Result<(), String>`

**前端调用**: `api.saveToSettings(config)`

---

### 6.2 reset_settings

**功能**: 重置 Claude Code 的 `settings.json` 配置文件为默认状态

**Rust 签名**:
```rust
pub fn reset_settings() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.resetSettings()`

---

### 6.3 open_settings_file

**功能**: 使用系统默认编辑器打开 Claude Code 的 `settings.json` 文件

**Rust 签名**:
```rust
pub fn open_settings_file() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `api.openSettingsFile()`

---

## 7. 应用配置 API

### 7.1 save_app_config

**功能**: 保存应用全局配置（旧版 API，用于向后兼容）

**Rust 签名**:
```rust
pub fn save_app_config(config: AppConfig) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `AppConfig` | 应用全局配置对象 |

**返回值**: `Result<(), String>`

**前端调用**: `api.saveAppConfig(config)`

---

### 7.2 load_app_config

**功能**: 加载应用全局配置（旧版 API，用于向后兼容）

**Rust 签名**:
```rust
pub fn load_app_config() -> Result<AppConfig, String>
```

**参数**: 无

**返回值**: `Result<AppConfig, String>`

**前端调用**: `api.loadAppConfig()`

---

## 8. 项目管理 API

### 8.1 get_projects

**功能**: 获取所有项目列表

**Rust 签名**:
```rust
pub fn get_projects() -> Result<Vec<Project>, String>
```

**参数**: 无

**返回值**: `Result<Vec<Project>, String>`

**前端调用**: `projectApi.getAll()`

---

### 8.2 get_project

**功能**: 根据 ID 获取单个项目

**Rust 签名**:
```rust
pub fn get_project(id: String) -> Result<Project, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |

**返回值**: `Result<Project, String>`

**前端调用**: `projectApi.get(id)`

---

### 8.3 create_project

**功能**: 创建新项目

**Rust 签名**:
```rust
pub fn create_project(name: String, working_directory: String, config: ProjectConfig) -> Result<Project, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `String` | 项目名称 |
| `working_directory` | `String` | 工作目录路径 |
| `config` | `ProjectConfig` | 项目配置 |

**返回值**: `Result<Project, String>` — 新创建的项目对象

**前端调用**: `projectApi.create(name, workingDirectory, config)`

---

### 8.4 update_project

**功能**: 更新现有项目（所有字段均为可选，仅更新传入的字段）

**Rust 签名**:
```rust
pub fn update_project(
    id: String,
    name: Option<String>,
    working_directory: Option<String>,
    config: Option<ProjectConfig>,
    is_pinned: Option<bool>
) -> Result<Project, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |
| `name` | `Option<String>` | 新项目名称 |
| `working_directory` | `Option<String>` | 新工作目录 |
| `config` | `Option<ProjectConfig>` | 新项目配置 |
| `is_pinned` | `Option<bool>` | 是否置顶 |

**返回值**: `Result<Project, String>` — 更新后的项目对象

**前端调用**: `projectApi.update(id, name?, workingDirectory?, config?, isPinned?)`

---

### 8.5 delete_project

**功能**: 删除指定项目

**Rust 签名**:
```rust
pub fn delete_project(id: String) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |

**返回值**: `Result<(), String>`

**前端调用**: `projectApi.delete(id)`

---

### 8.6 generate_project_powershell_command

**功能**: 根据项目 ID 生成 PowerShell 启动命令（包含工作目录切换）

**Rust 签名**:
```rust
pub fn generate_project_powershell_command(id: String) -> Result<String, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |

**返回值**: `Result<String, String>`

**前端调用**: `projectApi.generatePowershellCommand(id)`

---

### 8.7 generate_project_cmd_command

**功能**: 根据项目 ID 生成 CMD 启动命令（包含工作目录切换）

**Rust 签名**:
```rust
pub fn generate_project_cmd_command(id: String) -> Result<String, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |

**返回值**: `Result<String, String>`

**前端调用**: `projectApi.generateCmdCommand(id)`

---

### 8.8 generate_project_bash_command

**功能**: 根据项目 ID 生成 Bash 启动命令（包含工作目录切换）

**Rust 签名**:
```rust
pub fn generate_project_bash_command(id: String) -> Result<String, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |

**返回值**: `Result<String, String>`

**前端调用**: `projectApi.generateBashCommand(id)`

---

### 8.9 update_projects_order

**功能**: 批量更新项目排序顺序（拖拽排序后调用）

**Rust 签名**:
```rust
pub fn update_projects_order(orders: Vec<ProjectOrderItem>) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `orders` | `Vec<ProjectOrderItem>` | 项目 ID 与排序值的数组 |

**返回值**: `Result<(), String>`

**前端调用**: `projectApi.updateProjectsOrder(orders)`

---

### 8.10 update_pinned_order

**功能**: 批量更新置顶项目的排序顺序

**Rust 签名**:
```rust
pub fn update_pinned_order(orders: Vec<PinnedOrderItem>) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `orders` | `Vec<PinnedOrderItem>` | 置顶项目 ID 与置顶时间戳的数组 |

**返回值**: `Result<(), String>`

**前端调用**: `projectApi.updatePinnedOrder(orders)`

---

### 8.11 toggle_project_pinned

**功能**: 切换项目的置顶状态

**Rust 签名**:
```rust
pub fn toggle_project_pinned(id: String, is_pinned: bool) -> Result<Project, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `String` | 项目 UUID |
| `is_pinned` | `bool` | 是否置顶 |

**返回值**: `Result<Project, String>` — 更新后的项目对象

**前端调用**: `projectApi.togglePinned(id, isPinned)`

---

### 8.12 get_home_directory

**功能**: 获取当前用户的主目录路径

**Rust 签名**:
```rust
pub fn get_home_directory() -> Result<String, String>
```

**参数**: 无

**返回值**: `Result<String, String>`

**前端调用**: `systemApi.getHomeDirectory()`

---

## 9. 引导 API

### 9.1 get_onboarding_status

**功能**: 获取用户是否已完成新手引导

**Rust 签名**:
```rust
pub fn get_onboarding_status() -> Result<bool, String>
```

**参数**: 无

**返回值**: `Result<bool, String>` — `true` 表示已完成引导

**前端调用**: `onboardingApi.getStatus()`

---

### 9.2 set_onboarding_completed

**功能**: 标记新手引导为已完成

**Rust 签名**:
```rust
pub fn set_onboarding_completed() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `onboardingApi.setCompleted()`

---

## 10. Mobot Bridge 管理 API

### 10.1 detect_mobot_installation

**功能**: 检测 Mobot Bridge 的安装状态。如果已安装，还会确保捆绑资源（如 mingit/）存在于 bridge 目录中，并比较已安装版本与捆绑版本，版本不一致时返回 `NotInstalled` 以强制重新安装

**Rust 签名**:
```rust
pub async fn detect_mobot_installation(app_handle: tauri::AppHandle) -> InstallStatus
```

**参数**: 无（`app_handle` 由 Tauri 自动注入）

**返回值**: `InstallStatus` — `NotInstalled` | `Installed { path }` | `Running { path, port }`

**前端调用**: `mobotApi.detectInstallation()`

---

### 10.2 install_mobot_bridge

**功能**: 从应用捆绑资源安装 Mobot Bridge 到用户配置目录（`~/.config/mobot-launcher/mobot-bridge/`）

**Rust 签名**:
```rust
pub async fn install_mobot_bridge(app_handle: tauri::AppHandle) -> Result<String, String>
```

**参数**: 无（`app_handle` 由 Tauri 自动注入）

**返回值**: `Result<String, String>` — 安装路径

**前端调用**: `mobotApi.install()`

---

### 10.3 check_mobot_deps_installed

**功能**: 检查 Mobot Bridge 的 Python 依赖是否已安装

**Rust 签名**:
```rust
pub async fn check_mobot_deps_installed(bridge_path: String) -> bool
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `bridge_path` | `String` | Bridge 安装路径 |

**返回值**: `bool`

**前端调用**: `mobotApi.checkDepsInstalled(bridgePath)`

---

### 10.4 detect_python

**功能**: 检测系统中可用的 Python 解释器路径

**Rust 签名**:
```rust
pub async fn detect_python() -> Option<String>
```

**参数**: 无

**返回值**: `Option<String>` — Python 可执行文件路径，未找到时返回 `null`

**前端调用**: `mobotApi.detectPython()`

---

### 10.5 install_mobot_deps

**功能**: 安装 Mobot Bridge 的 Python 依赖（pip install），安装过程中通过 Tauri 事件向前端发送进度

**Rust 签名**:
```rust
pub async fn install_mobot_deps(app_handle: tauri::AppHandle, bridge_path: String, python: String) -> Result<String, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `bridge_path` | `String` | Bridge 安装路径 |
| `python` | `String` | Python 可执行文件路径 |

**返回值**: `Result<String, String>`

**前端调用**: `mobotApi.installDeps(bridgePath, python)`

---

### 10.6 start_mobot_service

**功能**: 启动 Mobot Bridge 服务（FastAPI + Claude Agent SDK），返回进程 PID

**Rust 签名**:
```rust
pub async fn start_mobot_service(bridge_path: String, python: String, port: u16) -> Result<u32, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `bridge_path` | `String` | Bridge 安装路径 |
| `python` | `String` | Python 可执行文件路径 |
| `port` | `u16` | 服务监听端口（默认 8000） |

**返回值**: `Result<u32, String>` — 服务进程 PID

**前端调用**: `mobotApi.startService(bridgePath, python, port)`

---

### 10.7 stop_mobot_service

**功能**: 停止正在运行的 Mobot Bridge 服务

**Rust 签名**:
```rust
pub async fn stop_mobot_service() -> Result<(), String>
```

**参数**: 无

**返回值**: `Result<(), String>`

**前端调用**: `mobotApi.stopService()`

---

### 10.8 check_mobot_health

**功能**: 检查 Mobot Bridge 服务的健康状态（调用 `/health` 端点）

**Rust 签名**:
```rust
pub async fn check_mobot_health(port: u16) -> HealthStatus
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `port` | `u16` | 服务端口 |

**返回值**: `HealthStatus` — `{ healthy: bool, details: String }`

**前端调用**: `mobotApi.checkHealth(port)`

---

### 10.9 get_mobot_status

**功能**: 获取 Mobot Bridge 服务的综合状态信息

**Rust 签名**:
```rust
pub async fn get_mobot_status(port: u16) -> MobotServiceStatus
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `port` | `u16` | 服务端口 |

**返回值**: `MobotServiceStatus`

**前端调用**: `mobotApi.getStatus(port)`

---

### 10.10 get_mobot_logs

**功能**: 获取 Mobot Bridge 服务的最近日志

**Rust 签名**:
```rust
pub async fn get_mobot_logs(max_lines: Option<usize>) -> Vec<String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `max_lines` | `Option<usize>` | 最大行数，默认 200 |

**返回值**: `Vec<String>` — 日志行数组

**前端调用**: `mobotApi.getLogs(maxLines?)`

---

### 10.11 is_mobot_updating

**功能**: 检查 Mobot Bridge 是否正在更新中

**Rust 签名**:
```rust
pub async fn is_mobot_updating() -> bool
```

**参数**: 无

**返回值**: `bool`

**前端调用**: `mobotApi.isUpdating()`

---

## 11. Claude 登录 API

### 11.1 check_claude_login

**功能**: 检查用户是否已登录 Claude（通过检测 `~/.claude` 目录是否存在）

**Rust 签名**:
```rust
pub fn check_claude_login() -> bool
```

**参数**: 无

**返回值**: `bool`

**前端调用**: `claudeLoginApi.checkLogin()`

---

### 11.2 launch_claude_for_login

**功能**: 启动 Claude Code CLI 用于登录认证，在用户主目录启动，可选配置代理

**Rust 签名**:
```rust
pub fn launch_claude_for_login(proxy: Option<String>) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `proxy` | `Option<String>` | 可选的 HTTP/HTTPS 代理地址 |

**返回值**: `Result<(), String>`

**前端调用**: `claudeLoginApi.launchForLogin(proxy?)`

---

## 12. CC 配置检查 API

### 12.1 scan_cc_config

**功能**: 扫描 Claude Code 配置文件，检测环境变量冲突、BOM 编码问题和 MCP 配置错位

**Rust 签名**:
```rust
pub fn scan_cc_config(projects: Vec<ProjectInfo>) -> ConfigScanResult
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `projects` | `Vec<ProjectInfo>` | 项目信息列表 `[{ name, working_directory }]` |

**返回值**: `ConfigScanResult` — `{ conflicts, bom_files, mcp_misplaced }`

**检查的环境变量 Key**: `HTTP_PROXY`, `HTTPS_PROXY`, `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`

**前端调用**: `ccConfigApi.scan(projects)`

---

### 12.2 clean_cc_config_field

**功能**: 清除配置文件中指定的单个环境变量字段

**Rust 签名**:
```rust
pub fn clean_cc_config_field(file_path: String, key: String) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `String` | 配置文件路径 |
| `key` | `String` | 要清除的环境变量 Key |

**返回值**: `Result<(), String>`

**前端调用**: `ccConfigApi.cleanField(filePath, key)`

---

### 12.3 clean_cc_config_all

**功能**: 批量清除多个配置文件中的环境变量字段

**Rust 签名**:
```rust
pub fn clean_cc_config_all(targets: Vec<CleanTarget>) -> Result<u32, String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `targets` | `Vec<CleanTarget>` | 清除目标数组 `[{ file_path, key }]` |

**返回值**: `Result<u32, String>` — 成功清除的数量

**前端调用**: `ccConfigApi.cleanAll(targets)`

---

### 12.4 open_cc_config_file

**功能**: 使用系统默认程序打开指定的配置文件

**Rust 签名**:
```rust
pub fn open_cc_config_file(file_path: String) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `String` | 配置文件路径 |

**返回值**: `Result<(), String>`

**前端调用**: `ccConfigApi.openFile(filePath)`

---

### 12.5 fix_cc_config_bom

**功能**: 修复配置文件的 UTF-8 BOM 编码问题（去除 BOM 头）

**Rust 签名**:
```rust
pub fn fix_cc_config_bom(file_path: String) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `String` | 配置文件路径 |

**返回值**: `Result<(), String>`

**前端调用**: `ccConfigApi.fixBom(filePath)`

---

### 12.6 fix_cc_mcp_misplaced

**功能**: 修复 MCP 配置错位问题（将错放在 settings.json 中的 mcpServers 移到正确的目标文件）

**Rust 签名**:
```rust
pub fn fix_cc_mcp_misplaced(file_path: String, target_path: String) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `String` | 源配置文件路径（包含错位的 MCP 配置） |
| `target_path` | `String` | 目标配置文件路径（正确的 MCP 配置位置） |

**返回值**: `Result<(), String>`

**前端调用**: `ccConfigApi.fixMcpMisplaced(filePath, targetPath)`

---

### 12.7 remove_cc_mcp_servers

**功能**: 从配置文件中移除 mcpServers 配置段

**Rust 签名**:
```rust
pub fn remove_cc_mcp_servers(file_path: String) -> Result<(), String>
```

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `String` | 配置文件路径 |

**返回值**: `Result<(), String>`

**前端调用**: `ccConfigApi.removeMcpServers(filePath)`

---

## 13. 便携模式 API

### 13.1 is_portable_mode

**功能**: 检测应用是否以便携模式运行（通过检测可执行文件旁边是否存在 `.portable` 标记文件）

**Rust 签名**:
```rust
pub fn is_portable_mode() -> bool
```

**参数**: 无

**返回值**: `bool`

**前端调用**: `invoke<boolean>('is_portable_mode')` （在 `useUpdateChecker` hook 中直接调用）

---

### 13.2 get_portable_download_url

**功能**: 获取便携版最新发布的下载 URL

**Rust 签名**:
```rust
pub fn get_portable_download_url() -> String
```

**参数**: 无

**返回值**: `String` — 固定返回 `"https://github.com/Earthling18/claude-code-launcher/releases/latest"`

**前端调用**: `invoke<string>('get_portable_download_url')` （在 `useUpdateChecker` hook 中直接调用）

---

## 14. 工具 API

### 14.1 get_hostname

**功能**: 获取当前机器的主机名

**Rust 签名**:
```rust
pub fn get_hostname() -> String
```

**参数**: 无

**返回值**: `String`

**前端调用**: `mobotApi.getHostname()`

---

### 14.2 get_username

**功能**: 获取当前操作系统用户名

**Rust 签名**:
```rust
pub fn get_username() -> String
```

**参数**: 无

**返回值**: `String`

**前端调用**: `mobotApi.getUsername()`

---

## 前端 API 模块索引

| 模块 | 导入路径 | 包含的命令 |
|------|----------|-----------|
| `api` | `import { api } from './api'` | 依赖检测、安装更新、启动、命令生成、平台检测、设置管理、应用配置 |
| `projectApi` | `import { projectApi } from './api'` | 项目 CRUD、启动、命令生成、排序、置顶 |
| `mobotApi` | `import { mobotApi } from './api'` | Bridge 安装、依赖、服务管理、健康检查、日志 |
| `ccConfigApi` | `import { ccConfigApi } from './api'` | 配置扫描、清理、修复 |
| `claudeLoginApi` | `import { claudeLoginApi } from './api'` | 登录检查、启动登录 |
| `dialogApi` | `import { dialogApi } from './api'` | 目录选择对话框 |
| `systemApi` | `import { systemApi } from './api'` | 主目录获取 |
| `onboardingApi` | `import { onboardingApi } from './api'` | 引导状态管理 |
