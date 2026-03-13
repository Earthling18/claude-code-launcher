# Mobot Launcher - Rust 后端开发指南

> **项目版本**: 1.0.4
> **最后更新**: 2026-03-13
> **技术栈**: Rust + Tauri 2

---

## 目录

- [1. 技术栈](#1-技术栈)
- [2. 项目结构](#2-项目结构)
- [3. 应用初始化 (lib.rs)](#3-应用初始化-librs)
- [4. Commands 层](#4-commands-层)
- [5. Services 层](#5-services-层)
- [6. 数据模型 (models/project.rs)](#6-数据模型-modelsprojectrs)
- [7. 配置文件 (tauri.conf.json)](#7-配置文件-tauriconfjson)
- [8. 依赖列表 (Cargo.toml)](#8-依赖列表-cargotoml)
- [9. 跨平台处理](#9-跨平台处理)

---

## 1. 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Rust | edition 2021 | 核心语言 |
| Tauri | 2 | 桌面框架，前后端通信 |
| tokio | 1 (full features) | 异步运行时，spawn_blocking 处理 IO 密集任务 |
| serde / serde_json | 1 | JSON 序列化/反序列化 |
| reqwest | 0.12 (json, blocking) | HTTP 客户端，检测最新版本、健康检查 |
| regex | 1 | 版本号解析 |
| base64 | 0.22 | Token 编解码存储 |
| dirs | 5.0 | 获取系统目录（home、config、data_local） |
| once_cell | 1 | 全局静态变量（进程跟踪） |
| log | 0.4 | 日志 |
| zip | 2 | 解压打包资源 |
| winreg | 0.52 | Windows 注册表操作（仅 Windows） |
| windows | 0.58 | Win32 API：SendMessageTimeout 广播环境变量变更（仅 Windows） |

**Tauri 插件**：

| 插件 | 版本 | 用途 |
|------|------|------|
| tauri-plugin-opener | 2 | 打开文件/URL |
| tauri-plugin-dialog | 2 | 原生目录选择对话框 |
| tauri-plugin-clipboard-manager | 2 | 剪贴板 |
| tauri-plugin-process | 2.3.1 | 进程信息（重启等） |
| tauri-plugin-updater | 2.10.0 | 自动更新（GitHub Releases） |

---

## 2. 项目结构

```
src-tauri/
├── Cargo.toml                  # Rust 依赖配置
├── tauri.conf.json             # Tauri 配置（v1.0.4）
├── build.rs                    # tauri-build
├── icons/                      # 应用图标
├── resources/
│   └── bridge/**/*             # mobot-bridge 打包资源
├── windows/
│   └── hooks.nsh               # NSIS 安装钩子
└── src/
    ├── main.rs                 # 入口，调用 lib::run()
    ├── lib.rs                  # 应用初始化、插件注册、command handler、RunEvent
    ├── commands/
    │   └── mod.rs              # 所有 Tauri command 定义（薄层，委托给 services）
    ├── models/
    │   ├── mod.rs              # pub mod project; pub use project::*
    │   └── project.rs          # Project、ProjectConfig 等数据模型
    └── services/
        ├── mod.rs              # 模块导出与 pub use
        ├── bridge_manager.rs   # Mobot Bridge 安装/启动/停止/健康检查
        ├── dependency_checker.rs # Node.js/Claude/Codex/Git 依赖检测
        ├── installer.rs        # 依赖一键安装/更新（跨平台脚本）
        ├── launcher.rs         # Claude/Codex CLI 启动与命令生成
        ├── config_storage.rs   # 项目 CRUD、配置持久化、v1→v2 迁移
        ├── cc_config_checker.rs # Claude Code 配置文件扫描/修复
        ├── settings_manager.rs # ~/.claude/settings.json 读写（旧版）
        └── environment.rs      # 环境变量持久化（Windows 注册表）
```

---

## 3. 应用初始化 (lib.rs)

`lib.rs` 导出 `pub fn run()`，由 `main.rs` 调用。

### 3.1 启动前环境清理

```rust
// 清除 CLAUDECODE 环境变量，防止子进程认为自己在嵌套 Claude Code 会话中
std::env::remove_var("CLAUDECODE");

// 确保 127.0.0.1 和 localhost 绕过 HTTP 代理（WebView2 读取 env vars）
// 向 NO_PROXY / no_proxy 追加 127.0.0.1,localhost
```

### 3.2 插件注册

```rust
tauri::Builder::default()
    .plugin(tauri_plugin_opener::init())
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_clipboard_manager::init())
    .plugin(tauri_plugin_process::init())
```

`tauri_plugin_updater` 在 `setup` 闭包中注册（仅 desktop 平台）：

```rust
.setup(|app| {
    #[cfg(desktop)]
    app.handle().plugin(tauri_plugin_updater::Builder::new().build())?;
    // ...
})
```

### 3.3 setup 逻辑

- **macOS 旧应用清理**：检测 `/Applications/Claude Code Launcher.app` 和 `~/Applications/Claude Code Launcher.app`，若存在则删除（品牌重命名迁移）。

### 3.4 Window 事件

```rust
.on_window_event(|_window, _event| {})  // 目前无处理逻辑
```

### 3.5 Command 注册

通过 `tauri::generate_handler!` 宏注册所有 command（共约 60 个），详见第 4 节。

### 3.6 RunEvent::Exit

```rust
.build(tauri::generate_context!())
.expect("error while building tauri application")
.run(|_app, event| {
    if let tauri::RunEvent::Exit = event {
        services::BridgeManager::stop_all();  // 退出时终止所有 bridge 进程
    }
});
```

使用 `.build().run()` 模式（而非 `.run()`），以便在 `run` 回调中处理 `RunEvent::Exit`。

---

## 4. Commands 层

所有 command 定义在 `commands/mod.rs`，每个 command 用 `#[tauri::command]` 标注，是薄层封装，委托给对应的 service。

### 4.1 依赖检测

| Command | 返回类型 | 说明 |
|---------|----------|------|
| `check_nodejs()` | `DependencyStatus` | 检测 Node.js（不联网） |
| `check_claude()` | `DependencyStatus` | 检测 Claude CLI |
| `check_gitbash()` | `DependencyStatus` | 检测 Git/Git Bash |
| `check_codex()` | `DependencyStatus` | 检测 Codex CLI |
| `check_nodejs_with_update()` | `DependencyStatus` | 检测 + 查询最新版本 |
| `check_claude_with_update()` | `DependencyStatus` | 检测 + 查询最新版本 |
| `check_gitbash_with_update()` | `DependencyStatus` | 检测 + 查询最新版本 |
| `check_codex_with_update()` | `DependencyStatus` | 检测 + 查询最新版本 |
| `refresh_system_path()` | `()` | 刷新 Windows 系统 PATH（仅 Windows） |

### 4.2 依赖安装/更新

| Command | 说明 |
|---------|------|
| `install_nodejs()` | 安装 Node.js |
| `update_nodejs()` | 更新 Node.js |
| `install_claude()` | 安装 Claude CLI |
| `update_claude()` | 更新 Claude CLI |
| `install_gitbash()` | 安装 Git Bash |
| `update_gitbash()` | 更新 Git Bash |
| `install_codex()` | 安装 Codex CLI |
| `update_codex()` | 更新 Codex CLI |

### 4.3 启动与命令生成

| Command | 参数 | 说明 |
|---------|------|------|
| `launch_claude_code(config)` | `HashMap<String, String>` | 直接启动 CLI |
| `generate_powershell_command(config)` | `HashMap<String, String>` | 生成 PowerShell 命令 |
| `generate_cmd_command(config)` | `HashMap<String, String>` | 生成 CMD 命令 |
| `generate_bash_command(config)` | `HashMap<String, String>` | 生成 Bash 命令 |

### 4.4 旧版设置（settings_manager）

| Command | 说明 |
|---------|------|
| `save_to_settings(config)` | 写入 `~/.claude/settings.json` |
| `reset_settings()` | 重置 settings.json |
| `open_settings_file()` | 用系统默认编辑器打开 |

### 4.5 应用配置（config_storage）

| Command | 说明 |
|---------|------|
| `save_app_config(config: AppConfig)` | 保存旧格式配置（v1 兼容） |
| `load_app_config()` | 加载旧格式配置 |

### 4.6 项目管理

| Command | 参数 | 返回 | 说明 |
|---------|------|------|------|
| `get_projects()` | - | `Vec<Project>` | 获取所有项目 |
| `get_project(id)` | `String` | `Project` | 获取单个项目 |
| `create_project(name, working_directory, config)` | 3 个参数 | `Project` | 创建项目 |
| `update_project(id, name?, working_directory?, config?, is_pinned?)` | 5 个参数 | `Project` | 更新项目 |
| `delete_project(id)` | `String` | `()` | 删除项目 |
| `launch_project(id)` | `String` | `()` | 启动项目（构建 config map + 调用 Launcher） |
| `select_directory(app_handle)` | `AppHandle` | `Option<String>` | 原生目录选择对话框 |
| `generate_project_powershell_command(id)` | `String` | `String` | 生成项目 PS 命令 |
| `generate_project_cmd_command(id)` | `String` | `String` | 生成项目 CMD 命令 |
| `generate_project_bash_command(id)` | `String` | `String` | 生成项目 Bash 命令 |
| `get_home_directory()` | - | `String` | 获取用户主目录 |
| `update_projects_order(orders)` | `Vec<ProjectOrderItem>` | `()` | 批量更新排序 |
| `update_pinned_order(orders)` | `Vec<PinnedOrderItem>` | `()` | 批量更新置顶排序 |
| `toggle_project_pinned(id, is_pinned)` | `String, bool` | `Project` | 切换置顶状态 |

`launch_project` 内部通过 `build_config_map()` 将 `Project` 转换为 `HashMap<String, String>`，根据 mode（claude/codex/custom）设置不同的环境变量键：

- **claude**: `HTTP_PROXY`, `HTTPS_PROXY`
- **codex**: `CLI_COMMAND=codex`, `HTTP_PROXY`, `HTTPS_PROXY`
- **custom (claude CLI)**: `ANTHROPIC_MODEL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`
- **custom (codex CLI)**: `CLI_COMMAND=codex --model ...`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`
- 通用: `SKIP_PERMISSIONS=true`（如果启用）

### 4.7 新手引导

| Command | 说明 |
|---------|------|
| `get_onboarding_status()` | 获取是否已完成引导 |
| `set_onboarding_completed()` | 标记引导完成 |

### 4.8 Mobot Bridge 管理

| Command | 参数 | 返回 | 说明 |
|---------|------|------|------|
| `detect_mobot_installation(app_handle)` | `AppHandle` | `InstallStatus` | 检测安装状态 + 版本比对 |
| `install_mobot_bridge(app_handle)` | `AppHandle` | `String` | 从 resources 安装到用户目录 |
| `check_mobot_deps_installed(bridge_path)` | `String` | `bool` | 检查依赖是否已安装 |
| `detect_python()` | - | `Option<String>` | 检测 Python 路径 |
| `install_mobot_deps(app_handle, bridge_path, python)` | 3 个参数 | `String` | 安装 Python 依赖 |
| `start_mobot_service(bridge_path, python, port)` | 3 个参数 | `u32` (PID) | 启动服务 |
| `stop_mobot_service()` | - | `()` | 停止服务 |
| `check_mobot_health(port)` | `u16` | `HealthStatus` | 健康检查 |
| `get_mobot_status(port)` | `u16` | `MobotServiceStatus` | 获取完整服务状态 |
| `get_mobot_logs(max_lines?)` | `Option<usize>` | `Vec<String>` | 获取日志（默认 200 行） |
| `is_mobot_updating()` | - | `bool` | 是否正在更新 |

`detect_mobot_installation` 额外包含：
1. 调用 `ensure_bundled_resources` 确保 mingit 等资源已同步到 bridge 目录
2. 比对 `VERSION` 文件和 `.mobot_version` 标记，版本不匹配时返回 `NotInstalled` 强制重装

### 4.9 Claude 登录检查

| Command | 说明 |
|---------|------|
| `check_claude_login()` | 检查 `~/.claude` 目录是否存在 |
| `launch_claude_for_login(proxy?)` | 启动 Claude CLI 以便用户登录 |

### 4.10 CC 配置检查

| Command | 参数 | 返回 | 说明 |
|---------|------|------|------|
| `scan_cc_config(projects)` | `Vec<ProjectInfo>` | `ConfigScanResult` | 扫描配置冲突 |
| `clean_cc_config_field(file_path, key)` | 2 个 `String` | `()` | 清理单个字段 |
| `clean_cc_config_all(targets)` | `Vec<CleanTarget>` | `u32` | 批量清理，返回清理数量 |
| `open_cc_config_file(file_path)` | `String` | `()` | 打开配置文件 |
| `fix_cc_config_bom(file_path)` | `String` | `()` | 修复 BOM 问题 |
| `fix_cc_mcp_misplaced(file_path, target_path)` | 2 个 `String` | `()` | 修复 MCP 配置错位 |
| `remove_cc_mcp_servers(file_path)` | `String` | `()` | 移除 MCP servers |

### 4.11 Portable 模式

| Command | 说明 |
|---------|------|
| `is_portable_mode()` | 检测 exe 同级目录是否存在 `.portable` 标记文件 |
| `get_portable_download_url()` | 返回 GitHub Releases 下载 URL |

### 4.12 工具命令

| Command | 说明 |
|---------|------|
| `get_platform()` | 返回 `"windows"` / `"macos"` / `"linux"` |
| `get_hostname()` | 获取主机名 |
| `get_username()` | 获取当前 OS 用户名 |

---

## 5. Services 层

### 5.1 bridge_manager.rs

管理 Mobot Bridge（Python FastAPI + Claude Agent SDK）的完整生命周期。

#### 类型定义

```rust
pub enum InstallStatus {
    NotInstalled,
    Installed { path: String },
    Running { path: String, port: u16 },
}

pub struct HealthStatus {
    pub healthy: bool,
    pub details: String,
}

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

#### 内部状态（全局 Mutex）

```rust
static MOBOT_PROCESS: Lazy<Mutex<Option<MobotProcess>>> = ...;
static BRIDGE_CLIENT_PROCESS: Lazy<Mutex<Option<Child>>> = ...;
static BRIDGE_CLIENT_STARTING: Lazy<Mutex<bool>> = ...;
static BRIDGE_CLIENT_LAST_FAIL: Lazy<Mutex<Option<Instant>>> = ...;
```

`MobotProcess` 内部跟踪：`child`、`port`、`started_at`、`install_path`、`python_path`、`logs`（最大 500 行 VecDeque）。

#### 公开函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_mobot_dir()` | `-> PathBuf` | 返回 `~/.config/mobot-launcher/mobot-bridge/`，自动从旧路径 `claude-launcher` 迁移 |
| `detect_installation()` | `-> InstallStatus` | 检查 `start.py` + `.mobot_version` + `.deps_installed` 是否存在 |
| `install_mobot_bridge(resource_dir)` | `-> Result<String, String>` | 从 resources 复制到用户目录，安装前先 `stop_all()` |
| `find_bridge_source_pub(resource_dir)` | `-> Result<PathBuf, String>` | 公开版的 bridge 资源目录查找 |
| `check_deps_installed(bridge_path)` | `-> bool` | 检查 `.deps_installed` 标记 |
| `detect_python()` | `-> Option<String>` | 检测可用的 Python 路径 |
| `install_dependencies(bridge_path, python, app_handle?)` | `-> Result<String, String>` | 安装 Python 依赖，可选通过 `app_handle` 发送 Tauri 事件 |
| `start_service(bridge_path, python, port)` | `-> Result<u32, String>` | 启动 bridge 服务，返回 PID |
| `stop_service()` | `-> Result<(), String>` | 停止当前跟踪的服务进程 |
| `ensure_bundled_resources(bridge_dir)` | `(bridge_dir: &Path)` | 确保 mingit 等打包资源已同步到 bridge 目录 |
| `check_health(port)` | `-> HealthStatus` | HTTP 请求 `/health` 端点 |
| `get_service_status(port)` | `-> MobotServiceStatus` | 聚合安装状态+运行状态+健康检查 |
| `get_logs(max_lines)` | `-> Vec<String>` | 获取内存中缓存的服务日志 |
| `stop_all()` | `()` | 终止所有 bridge 相关进程（app 退出时调用） |
| `get_hostname()` | `-> String` | 获取主机名 |
| `get_username()` | `-> String` | 获取当前 OS 用户名 |
| `is_updating()` | `-> bool` | 检查是否正在更新中 |

#### 关键内部函数

| 函数 | 说明 |
|------|------|
| `find_bridge_source(resource_dir)` | 在多个候选路径中查找 bridge 资源 |
| `find_resource_dir()` | 自动查找 resource 目录 |
| `kill_process_on_port(port)` | 杀掉占用指定端口的进程（仅 Windows） |
| `copy_dir_recursive(src, dst)` | 递归复制目录 |

### 5.2 dependency_checker.rs

检测 Node.js、Claude CLI、Codex CLI、Git/Git Bash 的安装状态和版本。

#### 类型定义

```rust
pub struct DependencyStatus {
    pub installed: bool,
    pub version: Option<String>,
    pub meets_requirement: bool,
    pub latest_version: Option<String>,
    pub update_available: bool,
    pub error: Option<String>,
}
```

#### 公开函数

| 函数 | 说明 |
|------|------|
| `check_nodejs()` | 检测 Node.js 是否安装及版本 |
| `check_claude()` | 检测 Claude CLI 是否安装及版本 |
| `check_codex()` | 检测 Codex CLI 是否安装及版本 |
| `check_gitbash()` | 检测 Git/Git Bash 是否安装及版本 |
| `check_nodejs_with_update()` | 检测 + 联网查询最新版本 |
| `check_claude_with_update()` | 检测 + 联网查询最新版本 |
| `check_codex_with_update()` | 检测 + 联网查询最新版本 |
| `check_gitbash_with_update()` | 检测 + 联网查询最新版本 |
| `refresh_system_path()` | 从 Windows 注册表重新读取 PATH（仅 Windows） |

#### 关键内部函数

| 函数 | 说明 |
|------|------|
| `check_dependency(...)` | 通用依赖检查逻辑 |
| `compare_versions(v1, v2)` | 语义版本比较 |
| `get_nodejs_latest_version()` | 从 nodejs.org API 获取最新版本 |
| `get_claude_latest_version()` | 从 npm registry 获取最新版本 |
| `get_codex_latest_version()` | 从 npm registry 获取最新版本 |
| `get_gitbash_latest_version()` | 从 GitHub API 获取最新版本 |
| `is_git_installer_running()` | 检测 Git 安装程序是否正在运行 |
| `get_macos_extended_path()` | macOS 扩展 PATH（包含 nvm/fnm/volta/homebrew 路径） |
| `hide_window(cmd)` | Windows 下隐藏控制台窗口 |

#### macOS PATH 扩展

由于 macOS GUI 应用不继承 shell PATH，`get_macos_extended_path()` 手动添加以下路径：
- `/usr/local/bin`、`/opt/homebrew/bin`、`/opt/homebrew/sbin`
- `~/.npm-global/bin`、`~/Library/pnpm`、`~/.local/bin`
- nvm: `~/.nvm/versions/node/*/bin`
- fnm: `~/Library/Application Support/fnm/node-versions/*/installation/bin`
- volta: `~/.volta/bin`

### 5.3 installer.rs

各依赖的安装/更新逻辑，全部通过生成平台脚本并执行。

#### 公开函数

| 函数 | Windows 实现 | macOS 实现 |
|------|-------------|-----------|
| `install_nodejs()` | PowerShell 脚本 | Terminal 脚本 |
| `update_nodejs()` | PowerShell 脚本 | Terminal 脚本 |
| `install_claude()` | CMD 脚本 | Terminal 脚本 |
| `update_claude()` | CMD 脚本 | Terminal 脚本 |
| `install_codex()` | CMD 脚本 | Terminal 脚本 |
| `update_codex()` | CMD 脚本 | Terminal 脚本 |
| `install_gitbash()` | PowerShell 脚本 | Terminal 脚本 |
| `update_gitbash()` | PowerShell 脚本 | Terminal 脚本 |

每个函数内部使用 `#[cfg(windows)]` / `#[cfg(target_os = "macos")]` 分支，调用对应平台的脚本生成和执行方法（`execute_powershell_script`、`execute_cmd_script`、`execute_terminal_script`）。

### 5.4 launcher.rs

启动 Claude/Codex CLI 并生成可复制的启动命令。

#### 公开函数

| 函数 | 说明 |
|------|------|
| `launch_with_config(config)` | 使用 config map 启动 CLI |
| `launch_with_config_and_dir(config, working_dir?)` | 指定工作目录启动 CLI |
| `launch_simple()` | 无配置直接启动 |
| `generate_powershell_command(config)` | 生成 PS 命令 |
| `generate_powershell_command_with_dir(config, working_dir?)` | 生成带目录的 PS 命令 |
| `generate_cmd_command(config)` | 生成 CMD 命令 |
| `generate_cmd_command_with_dir(config, working_dir?)` | 生成带目录的 CMD 命令 |
| `generate_bash_command(config)` | 生成 Bash 命令 |
| `generate_bash_command_with_dir(config, working_dir?)` | 生成带目录的 Bash 命令 |

#### 内部辅助

- `escape_ps_single_quotes()`: PowerShell 单引号转义
- `launcher_log_path()` / `launcher_transcript_path()` / `launcher_run_log_path()`: Windows 日志路径（`%LOCALAPPDATA%/ClaudeCodeLauncher/logs/`）
- `log_line()`: 写入启动日志

config map 中的特殊键：
- `CLI_COMMAND`: 指定 CLI 工具（默认 `claude`），可设为 `codex` 或 `codex --model xxx`
- `SKIP_PERMISSIONS`: 设为 `true` 时添加 `--dangerously-skip-permissions`
- 环境变量键: `HTTP_PROXY`、`HTTPS_PROXY`、`ANTHROPIC_*`、`OPENAI_*` 等

### 5.5 config_storage.rs

项目配置持久化，支持 v1→v2 自动迁移。

#### 类型定义

```rust
/// 旧版 v1 配置格式
pub struct AppConfig {
    pub mode: String,
    pub proxy: String,
    pub model: String,
    pub base_url: String,
    pub token: String,
    pub skip_permissions: bool,
}

/// v2 配置格式（多项目）
pub struct AppConfigV2 {
    pub version: u32,                   // 固定为 2
    pub projects: Vec<Project>,
    pub has_seen_onboarding: bool,
    pub mobot_bridge_port: u16,         // 默认 8000
}
```

#### 配置文件路径

- 新路径: `{config_dir}/MobotLauncher/config.json`
- 旧路径: `{config_dir}/ClaudeCodeLauncher/config.json`
- 自动迁移：旧目录存在且新目录不存在时，重命名旧目录

#### 公开函数

| 函数 | 说明 |
|------|------|
| `load_config_v2()` | 加载 v2 配置，自动从 v1 迁移 |
| `save_config_v2(config)` | 保存 v2 配置 |
| `get_projects()` | 获取所有项目列表 |
| `get_project(id)` | 按 ID 获取项目 |
| `create_project(input)` | 创建项目（自动分配 sort_order） |
| `update_project(id, updates)` | 更新项目字段 |
| `delete_project(id)` | 删除项目（禁止删除默认项目） |
| `update_project_launched(id)` | 更新 `last_launched_at` 时间戳 |
| `update_projects_order(orders)` | 批量更新 `sort_order` |
| `update_pinned_order(orders)` | 批量更新 `pinned_at` |
| `toggle_project_pinned(id, is_pinned)` | 切换置顶 |
| `get_onboarding_status()` | 获取引导完成状态 |
| `set_onboarding_completed()` | 标记引导完成 |
| `save_config(config: &AppConfig)` | 保存旧格式配置 |
| `load_config()` | 加载旧格式配置 |

#### Token 安全

- 存储时 Base64 编码（`encode_project_token`）
- 加载时 Base64 解码（`decode_project_token`）
- 同时处理 `token` 和 `codex_api_key` 字段

#### V1 → V2 迁移

`migrate_v1_to_v2()` 将旧的单项目配置转换为多项目格式：创建一个名为"默认项目"的 `Project`，工作目录为用户主目录。

### 5.6 cc_config_checker.rs

扫描和修复 Claude Code 配置文件中的冲突和问题。

#### 类型定义

```rust
pub struct ConfigConflict {
    pub source: String,
    pub file_path: Option<String>,
    pub key: String,
    pub value: String,        // 敏感值会被掩码处理
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

pub struct ConfigScanResult {
    pub conflicts: Vec<ConfigConflict>,
    pub bom_files: Vec<BomFileIssue>,
    pub mcp_misplaced: Vec<McpMisplaced>,
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

#### 扫描目标键

```rust
const TARGET_KEYS: &[&str] = &[
    "HTTP_PROXY", "HTTPS_PROXY",
    "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
];
```

#### 公开函数

| 函数 | 说明 |
|------|------|
| `scan_all(projects)` | 扫描所有项目配置，返回冲突、BOM 问题、MCP 错位 |
| `clean_field(file_path, key)` | 从指定文件删除指定键 |
| `clean_all(targets)` | 批量清理，返回成功数量 |
| `fix_bom(file_path)` | 移除文件的 UTF-8 BOM |
| `remove_mcp_servers(file_path)` | 移除 MCP servers 配置 |
| `fix_mcp_misplaced(file_path, target_path)` | 将错位的 MCP 配置移到正确位置 |
| `open_file(file_path)` | 用系统默认程序打开文件（macOS: `open`, Windows: `explorer`, Linux: `xdg-open`） |

#### 敏感值掩码

包含 `KEY` 或 `TOKEN` 的字段值会被掩码处理：显示前 6 字符 + `...` + 后 4 字符。

### 5.7 settings_manager.rs

操作 `~/.claude/settings.json` 文件（旧版设置管理）。

#### 公开函数

| 函数 | 说明 |
|------|------|
| `save_config(config: HashMap<String, String>)` | 写入 settings.json 的 `env` 字段 |
| `reset_config()` | 重置 settings.json |
| `open_settings_file()` | 用系统默认编辑器打开 |

配置路径: `~/.claude/settings.json`。操作前会检查 `~/.claude` 目录是否存在。

### 5.8 environment.rs

Windows 环境变量持久化工具。

#### 公开函数

| 函数 | 说明 |
|------|------|
| `set_permanent(key, value)` | 写入 Windows 注册表 `HKCU\Environment`，并广播 `WM_SETTINGCHANGE` |
| `get_env_keys()` | 返回管理的环境变量键列表 |

`set_permanent` 在非 Windows 平台返回 `Err("此功能仅在Windows上可用")`。

广播实现使用 `SendMessageTimeoutW` 向 `HWND_BROADCAST` 发送 `WM_SETTINGCHANGE`，超时 5 秒。

管理的环境变量键：

```
ANTHROPIC_MODEL, ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN,
HTTP_PROXY, HTTPS_PROXY
```

---

## 6. 数据模型 (models/project.rs)

### Project

```rust
pub struct Project {
    pub id: String,                      // 伪 UUID v4
    pub name: String,
    pub working_directory: String,
    pub config: ProjectConfig,
    pub is_default: bool,
    pub created_at: u64,                 // Unix 时间戳
    pub updated_at: u64,
    pub last_launched_at: Option<u64>,
    pub is_pinned: bool,
    pub pinned_at: Option<u64>,
    pub sort_order: u32,                 // 越小越靠前
}
```

工厂方法：
- `new(name, working_directory, config, is_default)`: 创建项目，自动生成 ID 和时间戳
- `new_with_sort_order(...)`: 创建项目并指定排序
- `default_project()`: 创建"默认项目"，工作目录为用户主目录，使用默认配置

### ProjectConfig

```rust
pub struct ProjectConfig {
    pub mode: String,                    // "claude" | "custom" | "codex" | "remote"
    pub proxy: String,
    pub model: String,                   // 默认 "qwen3-coder-480b-a35b"
    pub base_url: String,                // 默认 "http://litellm.uattest.weoa.com"
    pub token: String,                   // 存储时 Base64 编码
    pub skip_permissions: bool,          // 默认 true
    pub codex_api_key: String,           // Codex 代理（旧字段名保持兼容）
    pub custom_cli: String,              // "claude" | "codex"，默认 "claude"
    pub mobot_bridge_path: Option<String>,
    pub mobot_bridge_port: u16,          // 默认 8000
}
```

### 输入类型

```rust
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

pub struct ProjectOrderItem {
    pub id: String,
    pub sort_order: u32,
}

pub struct PinnedOrderItem {
    pub id: String,
    pub pinned_at: u64,
}
```

### UUID 生成

使用基于时间戳的伪 UUID v4（非密码学安全），格式符合 `xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx`。

---

## 7. 配置文件 (tauri.conf.json)

| 字段 | 值 | 说明 |
|------|-----|------|
| `productName` | `"Mobot Launcher"` | 应用名称 |
| `version` | `"1.0.4"` | 当前版本 |
| `identifier` | `"com.claudecode.launcher"` | 应用标识符 |
| `build.devUrl` | `http://localhost:1420` | 开发服务器 |
| `build.frontendDist` | `../dist` | 前端构建产物 |
| `app.windows[0]` | 750x700，最小 700x600，居中 | 主窗口配置 |
| `app.security.csp` | `null` | CSP 已禁用 |
| `bundle.targets` | `["nsis", "app", "dmg"]` | 构建目标：Windows NSIS、macOS App、macOS DMG |
| `bundle.publisher` | `"微众银行"` | 发布者 |
| `bundle.resources` | `["resources/bridge/**/*"]` | 打包的资源文件 |
| `bundle.createUpdaterArtifacts` | `true` | 生成更新产物 |
| `bundle.windows.webviewInstallMode` | `embedBootstrapper` | 内嵌 WebView2 引导安装 |
| `bundle.windows.nsis.installerHooks` | `./windows/hooks.nsh` | NSIS 自定义钩子 |
| `bundle.macOS.minimumSystemVersion` | `"10.13"` | macOS 最低版本 |
| `plugins.updater.endpoints` | GitHub Releases `latest.json` | 自动更新端点 |
| `plugins.updater.windows.installMode` | `"basicUi"` | Windows 更新 UI 模式 |

---

## 8. 依赖列表 (Cargo.toml)

### 通用依赖

```toml
tauri = { version = "2", features = [] }
tauri-plugin-opener = "2"
tauri-plugin-dialog = "2"
tauri-plugin-clipboard-manager = "2"
tauri-plugin-updater = "2.10.0"
tauri-plugin-process = "2.3.1"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tokio = { version = "1", features = ["full"] }
regex = "1"
base64 = "0.22"
reqwest = { version = "0.12", features = ["json", "blocking"] }
dirs = "5.0"
once_cell = "1"
log = "0.4"
zip = "2"
```

### Windows 专用依赖

```toml
[target.'cfg(windows)'.dependencies]
winreg = "0.52"
windows = { version = "0.58", features = [
    "Win32_Foundation",
    "Win32_UI_WindowsAndMessaging",
    "Win32_System_Threading"
] }
```

### 构建依赖

```toml
[build-dependencies]
tauri-build = { version = "2", features = [] }
```

### Crate 配置

```toml
[lib]
name = "mobot_launcher_tauri_lib"
crate-type = ["staticlib", "cdylib", "rlib"]
```

lib 名称带 `_lib` 后缀以避免 Windows 上 lib/bin 名称冲突（[cargo#8519](https://github.com/rust-lang/cargo/issues/8519)）。

---

## 9. 跨平台处理

项目大量使用条件编译处理平台差异：

### Windows (`#[cfg(windows)]`)

| 模块 | 功能 |
|------|------|
| `dependency_checker` | `CREATE_NO_WINDOW` 标志隐藏控制台窗口、`CommandExt::creation_flags`、`refresh_system_path` 从注册表读取 PATH、Git 安装程序检测 |
| `installer` | `execute_powershell_script` / `execute_cmd_script` 执行安装脚本 |
| `launcher` | 日志路径 `%LOCALAPPDATA%/ClaudeCodeLauncher/logs/`、`log_line` 写日志 |
| `environment` | 写入 `HKCU\Environment` 注册表、`SendMessageTimeoutW` 广播变更 |
| `bridge_manager` | `kill_process_on_port` 杀端口进程、MinGit 环境变量设置、Python 检测路径（Mobot 目录优先） |
| `cc_config_checker` | 配置文件路径规范化（反斜杠处理） |

### macOS (`#[cfg(target_os = "macos")]`)

| 模块 | 功能 |
|------|------|
| `lib.rs` | setup 中清理旧 `Claude Code Launcher.app` |
| `dependency_checker` | `get_macos_extended_path` 扩展 PATH（nvm/fnm/volta/homebrew）、xcode-select Git 检测 |
| `installer` | `execute_terminal_script` 执行安装脚本、Homebrew-free Node.js 安装 |
| `cc_config_checker` | `open` 命令打开文件 |

### Linux (`#[cfg(target_os = "linux")]`)

| 模块 | 功能 |
|------|------|
| `cc_config_checker` | `xdg-open` 打开文件 |

### 通用模式

- **installer.rs**: 所有安装函数使用三分支结构 `#[cfg(windows)]` / `#[cfg(target_os = "macos")]` / `#[cfg(all(not(windows), not(target_os = "macos")))]`（第三分支返回不支持错误）
- **dependency_checker.rs**: `hide_window()` 在 Windows 设置 `CREATE_NO_WINDOW`，其他平台为 no-op
- **environment.rs**: `set_permanent()` 仅 Windows 实现，其他平台返回错误
- **commands/mod.rs**: `get_platform()` 使用四分支返回平台字符串、`refresh_system_path()` 仅 Windows 执行
