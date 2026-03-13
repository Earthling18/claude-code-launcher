# Mobot Launcher Tauri - 完整技术文档

> **项目版本**: 1.0.4
> **最后更新**: 2026-03-13
> **技术栈**: Tauri 2 + React 19 + TypeScript + Rust + Python + Tailwind CSS

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 技术栈](#2-技术栈)
- [3. 项目结构](#3-项目结构)
- [4. 核心功能](#4-核心功能)
- [5. 架构设计](#5-架构设计)
- [6. 配置文件详解](#6-配置文件详解)
- [7. 构建与部署](#7-构建与部署)

---

## 1. 项目概述

### 1.1 项目简介

**Mobot Launcher** 是一个基于 Tauri 2 的桌面应用程序，为 Claude Code 及相关 CLI 工具提供图形化启动器，支持多项目管理和 5 种启动模式：

| 模式 | 说明 |
|------|------|
| **Claude 原版** (`claude`) | 通过代理访问 Claude 官方服务 |
| **自定义模型** (`custom`) | 使用自定义 API 端点和模型，支持 Claude CLI 或 Codex CLI |
| **Codex** (`codex`) | 使用 OpenAI Codex CLI |
| **远程 Bridge** (`remote`) | Python FastAPI + Claude Agent SDK，WebSocket 长连接至企微/飞书 |
| **Mobot** | 通过 Bridge 管理完整的 Agent 服务 |

### 1.2 核心价值

- **依赖管理**: 自动检测、安装和更新 Node.js、Claude Code、Git、Codex
- **多项目管理**: CRUD、拖拽排序、置顶
- **一键启动**: 简化 CLI 工具的环境变量配置和启动流程
- **远程桥接**: Python 后端运行 Agent 服务，安装/热更新/健康检查/自动资源释放
- **CC 配置检查器**: 扫描和修复 Claude Code 配置冲突、BOM、MCP 错位
- **自动更新**: 基于 Tauri Updater 的 GitHub Releases 自动更新
- **便携模式**: `.portable` 标记文件检测，支持免安装运行
- **新手引导**: OnboardingOverlay 组件提供首次使用引导
- **进程清理**: `RunEvent::Exit` 时调用 `BridgeManager::stop_all()` 清理子进程

---

## 2. 技术栈

### 2.1 前端技术

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 19.1.0 | UI 框架 |
| TypeScript | ~5.8.3 | 类型安全 |
| Vite | ^7.0.4 | 构建工具 |
| Tailwind CSS | ^3.4.0 | 样式框架 |
| @tauri-apps/api | ^2.10.1 | Tauri 前端 API |
| @dnd-kit/core | ^6.3.1 | 拖拽排序核心 |
| @dnd-kit/sortable | ^10.0.0 | 拖拽排序 |
| react-router-dom | ^7.13.0 | 前端路由 |

### 2.2 前端 Tauri 插件

| 插件 | 用途 |
|------|------|
| @tauri-apps/plugin-opener | 打开外部链接/文件 |
| @tauri-apps/plugin-clipboard-manager | 剪贴板操作 |
| @tauri-apps/plugin-process | 进程管理 |
| @tauri-apps/plugin-updater | 自动更新 |

### 2.3 后端技术 (Rust)

| 技术 | 版本 | 用途 |
|------|------|------|
| Tauri | 2 | 跨平台桌面框架 |
| tauri-plugin-opener | 2 | 打开外部链接 |
| tauri-plugin-dialog | 2 | 原生对话框 |
| tauri-plugin-clipboard-manager | 2 | 剪贴板 |
| tauri-plugin-updater | 2.10.0 | 自动更新 |
| tauri-plugin-process | 2.3.1 | 进程管理 |
| Tokio | 1 (full) | 异步运行时 |
| Serde / serde_json | 1 | 序列化/反序列化 |
| Reqwest | 0.12 (json, blocking) | HTTP 客户端 |
| regex | 1 | 正则表达式 |
| base64 | 0.22 | Base64 编解码 |
| dirs | 5.0 | 跨平台目录路径 |
| zip | 2 | ZIP 解压 |
| winreg | 0.52 | Windows 注册表 (仅 Windows) |
| windows | 0.58 | Win32 API (仅 Windows) |

### 2.4 远程桥接 (Python)

| 技术 | 用途 |
|------|------|
| FastAPI | Agent HTTP API 服务 |
| Claude Agent SDK | Claude SDK 交互 |
| Python 3.11 嵌入式 | Windows 内置运行时 |

---

## 3. 项目结构

以下目录树基于实际代码库中的文件：

```
D:\DEV\claude-code-launcher-tauri\
|
+-- .github/
|   +-- workflows/
|       +-- build.yml                    # CI/CD 自动化构建（Windows + macOS）
|
+-- src/                                 # 前端源码 (React + TypeScript)
|   +-- main.tsx                         # React 入口
|   +-- App.tsx                          # 主应用组件（路由、拖拽上下文、更新通知）
|   +-- index.css                        # 全局样式 (Tailwind)
|   +-- api.ts                           # Tauri IPC 封装（api / projectApi / mobotApi / ccConfigApi / claudeLoginApi）
|   +-- types.ts                         # 通用类型（DependencyStatus, AppConfig, MODEL_OPTIONS）
|   +-- vite-env.d.ts                    # Vite 类型声明
|   |
|   +-- types/
|   |   +-- project.ts                   # 项目数据模型（Project, ProjectConfig, InstallStatus, ConfigScanResult 等）
|   |
|   +-- pages/
|   |   +-- ModeSelectPage.tsx           # 模式选择页（本地 / 远程桥接入口）
|   |   +-- ProjectListPage.tsx          # 项目列表页（拖拽排序、置顶、搜索）
|   |   +-- ProjectCreatePage.tsx        # 新建项目页
|   |   +-- ProjectEditPage.tsx          # 编辑项目页
|   |   +-- ProjectDetailPage.tsx        # 项目详情页（启动、命令生成）
|   |   +-- RemoteBridgePage.tsx         # 远程桥接管理页（安装、启停、日志、配置）
|   |
|   +-- components/
|   |   +-- ConfigPanel.tsx              # 启动模式配置面板
|   |   +-- DependencyFrame.tsx          # 依赖检测面板（Node.js / Claude / Git / Codex）
|   |   +-- ProjectCard.tsx              # 项目卡片组件
|   |   +-- SortableProjectCard.tsx      # 可拖拽项目卡片（@dnd-kit）
|   |   +-- ProjectForm.tsx              # 项目表单（含模式选择、置顶开关）
|   |   +-- DirectoryPicker.tsx          # 目录选择器
|   |   +-- ConfirmDialog.tsx            # 确认对话框
|   |   +-- ModeSwitch.tsx              # 本地/远程模式切换
|   |   +-- LocalSetupWizard.tsx         # 本地模式安装向导
|   |   +-- MobotSetupWizard.tsx         # Mobot Bridge 安装向导
|   |   +-- CcConfigPanel.tsx            # CC 配置检查器面板
|   |   +-- OnboardingOverlay.tsx        # 新手引导遮罩
|   |   +-- OnboardingTrigger.tsx        # 新手引导触发按钮
|   |   +-- UpdateNotification.tsx       # 自动更新通知条
|   |
|   +-- hooks/
|   |   +-- useUpdateChecker.ts          # 自动更新检查 Hook
|   |
|   +-- assets/
|       +-- react.svg
|       +-- ailing-qrcode.png            # 艾灵企微二维码
|
+-- src-tauri/                           # 后端源码 (Rust)
|   +-- Cargo.toml                       # Rust 依赖配置
|   +-- tauri.conf.json                  # Tauri 应用配置
|   +-- build.rs                         # Tauri 构建脚本
|   |
|   +-- src/
|   |   +-- main.rs                      # Rust 入口（主函数）
|   |   +-- lib.rs                       # Tauri 应用构建（插件注册、Commands 注册、RunEvent 处理）
|   |   |
|   |   +-- commands/
|   |   |   +-- mod.rs                   # 所有 Tauri Commands（依赖检测、安装、启动、项目管理、Bridge、CC 配置、便携模式）
|   |   |
|   |   +-- models/
|   |   |   +-- mod.rs                   # 模块导出
|   |   |   +-- project.rs              # 数据模型（Project, ProjectConfig, CreateProjectInput, UpdateProjectInput 等）
|   |   |
|   |   +-- services/
|   |       +-- mod.rs                   # 模块导出
|   |       +-- dependency_checker.rs    # 依赖检测（Node.js / Claude / Git / Codex，含版本更新检查）
|   |       +-- installer.rs            # 安装/更新服务（winget / npm / brew）
|   |       +-- launcher.rs             # 启动器（EncodedCommand、PowerShell/CMD/Bash 命令生成）
|   |       +-- settings_manager.rs     # Claude 设置管理（~/.claude/settings.json）
|   |       +-- config_storage.rs       # 应用配置存储（V2 多项目、迁移、Onboarding）
|   |       +-- environment.rs          # 环境变量管理
|   |       +-- bridge_manager.rs       # Bridge 进程管理（安装、启停、健康检查、日志、嵌入式 Python、MinGit）
|   |       +-- cc_config_checker.rs    # CC 配置检查器（冲突扫描、BOM 修复、MCP 错位修复）
|   |
|   +-- resources/bridge/               # Python 桥接资源（随应用打包）
|   |   +-- start.py                    # Bridge 启动脚本
|   |   +-- update.py                   # 热更新脚本
|   |   +-- restart_helper.py           # 重启辅助脚本
|   |   +-- clear_user_session.py       # 用户会话清理
|   |   +-- requirements.txt            # Python 依赖
|   |   +-- VERSION                     # Bridge 版本号（用于热更新版本比对）
|   |   +-- cron_jobs.json              # 定时任务配置
|   |   +-- cron_jobs.example.json      # 定时任务示例
|   |   +-- app/                        # FastAPI Agent 服务代码
|   |   +-- bridge/                     # WebSocket 桥接客户端代码
|   |   +-- mingit/                     # MinGit（Windows 便携 Git）
|   |   +-- python-embed/              # Python 3.11 嵌入式发行版
|   |   +-- wheels/                     # 预构建 Python .whl 依赖包（离线安装）
|   |
|   +-- capabilities/                   # Tauri 权限配置
|   +-- icons/                          # 应用图标（多尺寸 PNG + ICO + ICNS）
|   +-- windows/                        # NSIS 安装器钩子
|
+-- docs/                               # 项目文档
+-- public/                             # 静态资源
+-- package.json                        # NPM 配置
+-- vite.config.ts                      # Vite 配置
+-- tailwind.config.js                  # Tailwind CSS 配置
+-- postcss.config.js                   # PostCSS 配置
+-- tsconfig.json                       # TypeScript 配置
+-- tsconfig.node.json                  # Node 环境 TS 配置
```

### 3.1 目录职责

| 目录 | 职责 |
|------|------|
| `src/` | React 前端代码，处理 UI 和用户交互 |
| `src/pages/` | 6 个页面组件，对应前端路由 |
| `src/components/` | 14 个通用组件 |
| `src/hooks/` | 自定义 React Hooks |
| `src/types/` | TypeScript 类型定义 |
| `src-tauri/src/commands/` | Tauri Commands 层，IPC 接口定义 |
| `src-tauri/src/services/` | 7 个核心业务服务模块 |
| `src-tauri/src/models/` | Rust 数据模型 |
| `src-tauri/resources/bridge/` | Python 桥接服务代码和资源，随应用打包分发 |

---

## 4. 核心功能

### 4.1 依赖管理

检测并管理以下依赖项：

| 依赖 | 检测命令 | 安装方式 |
|------|----------|----------|
| Node.js | `node --version` | Windows: `winget install OpenJS.NodeJS.LTS`; macOS: 直接下载安装 |
| Claude Code | `claude --version` / `npm list -g` | `npm install -g @anthropic-ai/claude-code` |
| Git / Git Bash | `git --version` | Windows: `winget install Git.Git`; macOS: `xcode-select --install` |
| Codex | `codex --version` | `npm install -g @openai/codex` |

每项依赖提供两种检测模式：
- **快速检测** (`check_*`): 仅检查本地安装状态和版本
- **含更新检测** (`check_*_with_update`): 额外查询最新版本，判断是否有可用更新

`DependencyStatus` 数据结构：
```typescript
interface DependencyStatus {
  installed: boolean;
  version: string | null;
  meets_requirement: boolean;
  latest_version: string | null;
  update_available: boolean;
  error: string | null;
}
```

特性：
- npm shim 自动修复（`claude.cmd` 丢失但包已安装时静默重建）
- `refresh_system_path`: Windows 从注册表刷新 PATH 环境变量
- macOS: Homebrew-free Node.js 安装、xcode-select 优先的 Git 安装

### 4.2 多项目管理

#### 数据模型

**前端 (TypeScript)**:
```typescript
interface Project {
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

interface ProjectConfig {
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

**后端 (Rust)** 与前端数据结构一一对应，通过 Serde 自动序列化/反序列化。

#### 项目 CRUD

通过 `projectApi` 调用对应 Tauri Commands：
- `get_projects` / `get_project` / `create_project` / `update_project` / `delete_project`
- `launch_project`: 启动项目并更新 `last_launched_at`

#### 拖拽排序与置顶

排序优先级：
1. 默认项目 (`is_default = true`) — 固定第一位，不可拖拽
2. 置顶项目 (`is_pinned = true`) — 按 `pinned_at` 时间倒序，可互换
3. 普通项目 — 按 `sort_order` 排序，可互换

API：
- `update_projects_order`: 批量更新普通项目排序
- `update_pinned_order`: 批量更新置顶项目排序
- `toggle_project_pinned`: 切换置顶状态

#### 拖拽创建项目

App.tsx 监听 `tauri://drag-drop` 事件，将文件夹拖入窗口自动导航到新建项目页面。

### 4.3 5 种启动模式

根据 `ProjectConfig.mode` 和 `custom_cli` 字段，`build_config_map` 函数生成不同的环境变量：

| 模式 | 环境变量 |
|------|----------|
| `claude` | `HTTP_PROXY` / `HTTPS_PROXY`（如配置代理） |
| `codex` | `CLI_COMMAND=codex` + `HTTP_PROXY`/`HTTPS_PROXY`（如配置） |
| `custom` + `custom_cli=claude` | `ANTHROPIC_MODEL` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` |
| `custom` + `custom_cli=codex` | `CLI_COMMAND=codex --model X` / `OPENAI_BASE_URL` / `OPENAI_API_KEY` |
| `remote` | 通过 Bridge 管理，不直接启动 CLI |

所有模式支持 `skip_permissions`（添加 `--dangerously-skip-permissions`）。

命令生成支持 3 种格式：
- **PowerShell**: `Set-Location -LiteralPath '...'; $env:VAR='val'; claude ...`
- **CMD**: `cd /d "..." & set VAR=val & claude ...`
- **Bash**: `cd "..." && export VAR="val" && claude ...`

### 4.4 远程 Bridge（Mobot Bridge）

#### 安装与热更新

1. `detect_mobot_installation`: 检测安装状态，比对 `VERSION` 与 `.mobot_version` 判断是否需要重装
2. `install_mobot_bridge`: 从 `resources/bridge/` 复制文件到用户数据目录
3. `ensure_bundled_resources`: 确保 MinGit 等资源存在于 Bridge 目录
4. 版本不匹配时自动返回 `NotInstalled` 触发重装（热更新机制）

#### 服务生命周期

```
detect_python → install_mobot_deps → start_mobot_service → check_mobot_health → stop_mobot_service
```

- `detect_python`: 检测系统 Python 或使用嵌入式 Python
- `install_mobot_deps`: 安装 Python 依赖（支持离线 wheels）
- `start_mobot_service`: 启动 FastAPI 服务
- `check_mobot_health` / `get_mobot_status`: 健康检查
- `get_mobot_logs`: 获取服务日志
- `is_mobot_updating`: 检查是否正在更新

`InstallStatus` 枚举：
```typescript
type InstallStatus =
  | 'NotInstalled'
  | { Installed: { path: string } }
  | { Running: { path: string; port: number } };
```

#### 进程清理

`lib.rs` 中 `RunEvent::Exit` 事件触发 `BridgeManager::stop_all()`，确保应用退出时清理所有 Bridge 子进程。

#### 嵌入式 Python 方案

Windows 版本内置 Python 3.11 嵌入式发行版：
- `resources/bridge/python-embed/` — 嵌入式 Python（`.exe` 重命名为 `.bin` 绕过 gitignore）
- `resources/bridge/wheels/` — 预构建 `.whl` 依赖包
- `bridge_manager.rs` 复制到用户目录后自动将 `.bin` 重命名回 `.exe`

### 4.5 CC 配置检查器

通过 `ccConfigApi` 调用：

| 命令 | 功能 |
|------|------|
| `scan_cc_config` | 扫描所有项目的 CC 配置冲突 |
| `clean_cc_config_field` | 清理单个配置字段 |
| `clean_cc_config_all` | 批量清理 |
| `open_cc_config_file` | 打开配置文件 |
| `fix_cc_config_bom` | 修复 BOM 编码问题 |
| `fix_cc_mcp_misplaced` | 修复 MCP 配置错位 |
| `remove_cc_mcp_servers` | 移除 MCP 服务器配置 |

扫描结果包含：
```typescript
interface ConfigScanResult {
  conflicts: ConfigConflict[];  // 配置冲突
  bom_files: BomFileIssue[];   // BOM 编码问题
  mcp_misplaced: McpMisplaced[]; // MCP 错位
}
```

### 4.6 自动更新

基于 Tauri Updater 插件：
- 更新端点: `https://github.com/erthman18/claude-code-launcher/releases/latest/download/latest.json`
- 签名验证: 使用 `TAURI_SIGNING_PRIVATE_KEY` 签名
- Windows 安装模式: `basicUi`
- 便携模式检测: `is_portable_mode` 检查 `.portable` 文件，便携模式下引导用户手动下载

前端通过 `useUpdateChecker` Hook 管理更新状态，`UpdateNotification` 组件展示更新通知。

### 4.7 便携模式

- 检测: 可执行文件同级目录存在 `.portable` 标记文件
- `is_portable_mode`: 返回是否为便携模式
- `get_portable_download_url`: 返回最新便携版下载地址
- CI/CD 自动生成便携 ZIP 包

### 4.8 新手引导

- `OnboardingOverlay`: 全屏引导遮罩组件
- `OnboardingTrigger`: 重新触发引导的按钮
- 状态持久化: `get_onboarding_status` / `set_onboarding_completed`（通过 ConfigStorage）

### 4.9 Claude 登录检查

- `check_claude_login`: 检查 `~/.claude` 目录是否存在
- `launch_claude_for_login`: 启动 Claude CLI 用于登录（支持代理）

---

## 5. 架构设计

### 5.1 整体架构

```
+-----------------------------------------------------------+
|                     User Interface                         |
|                   (React 19 + Tailwind CSS)                |
|                                                            |
|  Pages:                    Components:                     |
|  - ModeSelectPage          - DependencyFrame               |
|  - ProjectListPage         - ConfigPanel                   |
|  - ProjectCreatePage       - ProjectCard/SortableCard      |
|  - ProjectEditPage         - ProjectForm                   |
|  - ProjectDetailPage       - MobotSetupWizard              |
|  - RemoteBridgePage        - CcConfigPanel                 |
|                            - UpdateNotification            |
+-----------------------------------------------------------+
                         | invoke()
                         v
+-----------------------------------------------------------+
|                    API Layer (api.ts)                       |
|  api / projectApi / mobotApi / ccConfigApi / claudeLoginApi |
+-----------------------------------------------------------+
                         | Tauri IPC
                         v
+-----------------------------------------------------------+
|                  Tauri Commands (commands/mod.rs)           |
|  70+ registered commands                                   |
+-----------------------------------------------------------+
                         |
                         v
+-----------------------------------------------------------+
|                   Services Layer                           |
|                                                            |
|  +-------------------+  +---------------+  +------------+  |
|  | dependency_checker|  | installer     |  | launcher   |  |
|  +-------------------+  +---------------+  +------------+  |
|                                                            |
|  +-------------------+  +---------------+  +------------+  |
|  | settings_manager  |  | config_storage|  | environment|  |
|  +-------------------+  +---------------+  +------------+  |
|                                                            |
|  +-------------------+  +-----------------------------+    |
|  | bridge_manager    |  | cc_config_checker           |    |
|  +-------------------+  +-----------------------------+    |
+-----------------------------------------------------------+
                         |
                         v
+-----------------------------------------------------------+
|                System Integration                          |
|  Windows: Registry, winget, cmd.exe, PowerShell            |
|  macOS: xcode-select, brew, Terminal                       |
|  Cross: npm, Node.js, File System, HTTP                    |
+-----------------------------------------------------------+
                         |
                         v
+-----------------------------------------------------------+
|              Python Bridge (远程模式)                       |
|  FastAPI Agent Server <-> WebSocket Bridge Client          |
|  Claude Agent SDK <-> 企微/飞书                             |
+-----------------------------------------------------------+
```

### 5.2 数据流

```
用户操作
  -> React Component (useState/useEffect)
    -> api.ts invoke()
      -> Tauri IPC
        -> commands/mod.rs (参数解析、类型转换)
          -> services/*.rs (业务逻辑)
            -> 系统调用 / 文件 IO / HTTP
          <- Result<T, String>
        <- JSON 序列化
      <- Promise<T>
    <- 状态更新
  <- UI 刷新
```

### 5.3 前端路由

定义在 `App.tsx`，使用 React Router 7：

| 路径 | 组件 | 说明 |
|------|------|------|
| `/` | `ModeSelectPage` | 模式选择（本地 / 远程桥接） |
| `/local` | `ProjectListPage` | 项目列表 |
| `/local/project/new` | `ProjectCreatePage` | 新建项目 |
| `/local/project/:id` | `ProjectDetailPage` | 项目详情 |
| `/local/project/:id/edit` | `ProjectEditPage` | 编辑项目 |
| `/remote` | `RemoteBridgePage` | 远程桥接管理 |

### 5.4 Tauri Commands 分类

lib.rs 中注册的 Commands 按功能分组：

| 分类 | 命令数 | 示例 |
|------|--------|------|
| 依赖检测 | 10 | `check_nodejs`, `check_claude_with_update`, `refresh_system_path` |
| 安装/更新 | 8 | `install_nodejs`, `update_claude`, `install_codex` |
| 启动器 | 4 | `launch_claude_code`, `generate_powershell_command` |
| 平台/设置 | 5 | `get_platform`, `save_to_settings`, `save_app_config` |
| 项目管理 | 12 | `get_projects`, `create_project`, `launch_project`, `toggle_project_pinned` |
| 引导 | 2 | `get_onboarding_status`, `set_onboarding_completed` |
| Bridge 管理 | 11 | `install_mobot_bridge`, `start_mobot_service`, `check_mobot_health` |
| Claude 登录 | 2 | `check_claude_login`, `launch_claude_for_login` |
| CC 配置检查 | 7 | `scan_cc_config`, `fix_cc_config_bom`, `fix_cc_mcp_misplaced` |
| 便携模式 | 2 | `is_portable_mode`, `get_portable_download_url` |
| 工具 | 2 | `get_hostname`, `get_username` |

### 5.5 Rust 模块依赖

```
main.rs
  +-- lib.rs
      +-- models/
      |   +-- project.rs  (Project, ProjectConfig, CreateProjectInput, ...)
      +-- commands/
      |   +-- mod.rs      (所有 #[tauri::command] 函数)
      +-- services/
          +-- dependency_checker.rs  (DependencyChecker)
          +-- installer.rs          (Installer)
          +-- launcher.rs           (Launcher)
          +-- settings_manager.rs   (SettingsManager)
          +-- config_storage.rs     (ConfigStorage, AppConfig)
          +-- environment.rs        (环境变量辅助)
          +-- bridge_manager.rs     (BridgeManager)
          +-- cc_config_checker.rs  (CcConfigChecker)
```

---

## 6. 配置文件详解

### 6.1 tauri.conf.json

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "Mobot Launcher",
  "version": "1.0.4",
  "identifier": "com.claudecode.launcher",
  "build": {
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://localhost:1420",
    "beforeBuildCommand": "npm run build",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [{
      "title": "Mobot Launcher",
      "width": 750, "height": 700,
      "minWidth": 700, "minHeight": 600,
      "resizable": true, "center": true
    }],
    "security": { "csp": null }
  },
  "bundle": {
    "active": true,
    "targets": ["nsis", "app", "dmg"],
    "publisher": "微众银行",
    "copyright": "版权所有 (c) 2026",
    "resources": ["resources/bridge/**/*"],
    "icon": ["icons/32x32.png", "icons/128x128.png", "icons/128x128@2x.png", "icons/icon.icns", "icons/icon.ico"],
    "macOS": { "minimumSystemVersion": "10.13" },
    "createUpdaterArtifacts": true,
    "windows": {
      "webviewInstallMode": { "type": "embedBootstrapper" },
      "nsis": { "installerHooks": "./windows/hooks.nsh" }
    }
  },
  "plugins": {
    "updater": {
      "pubkey": "...(ed25519 公钥)...",
      "endpoints": ["https://github.com/erthman18/claude-code-launcher/releases/latest/download/latest.json"],
      "windows": { "installMode": "basicUi" }
    }
  }
}
```

关键说明：
- `resources: ["resources/bridge/**/*"]`: 将 Bridge 资源打包到应用内
- `webviewInstallMode: embedBootstrapper`: 内嵌 WebView2 安装程序
- `nsis.installerHooks`: 自定义 NSIS 安装器钩子
- `createUpdaterArtifacts: true`: 生成自动更新签名文件

### 6.2 vite.config.ts

```typescript
export default defineConfig(async () => ({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
  },
}));
```

- 固定端口 1420，与 `tauri.conf.json` 的 `devUrl` 一致
- 支持 `TAURI_DEV_HOST` 环境变量用于远程开发
- 忽略 `src-tauri/` 目录的文件变更

### 6.3 package.json

```json
{
  "name": "mobot-launcher-tauri",
  "version": "1.0.4",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "tauri": "tauri",
    "tauri:dev": "tauri dev",
    "tauri:build": "tauri build",
    "tauri:build-clean": "tauri build -- --clean"
  }
}
```

### 6.4 应用数据配置

应用配置存储在 `%APPDATA%\ClaudeCodeLauncher\config.json`（Windows）或 `~/Library/Application Support/ClaudeCodeLauncher/config.json`（macOS）：

```json
{
  "version": 2,
  "projects": [
    {
      "id": "uuid",
      "name": "默认项目",
      "working_directory": "C:\\Users\\username",
      "config": {
        "mode": "claude",
        "proxy": "",
        "model": "qwen3-coder-480b-a35b",
        "base_url": "http://litellm.uattest.weoa.com",
        "token": "",
        "skip_permissions": true,
        "codex_api_key": "",
        "custom_cli": "claude",
        "mobot_bridge_path": null,
        "mobot_bridge_port": 8000
      },
      "is_default": true,
      "is_pinned": false,
      "sort_order": 0,
      "created_at": 1706918400,
      "updated_at": 1706918400
    }
  ]
}
```

支持 V1 到 V2 自动迁移。Token 使用 Base64 编码存储。

---

## 7. 构建与部署

### 7.1 开发环境

```bash
# 前置要求
node --version    # >= 18.0.0
rustc --version   # stable

# 安装依赖
npm install

# 启动开发模式
npm run tauri:dev
```

Vite 开发服务器启动在 `http://localhost:1420`，Tauri 自动打开桌面窗口，支持前端热重载。

### 7.2 构建生产版本

```bash
npm run tauri:build
```

步骤：
1. `tsc` 编译 TypeScript
2. `vite build` 构建前端到 `dist/`
3. `cargo build --release` 编译 Rust
4. Tauri 打包生成安装程序

### 7.3 CI/CD (GitHub Actions)

工作流文件: `.github/workflows/build.yml`

触发条件：
- 推送 `v*` 标签
- 手动触发 (`workflow_dispatch`)

构建流程：

```
check-version (ubuntu)
  |-- 校验 tauri.conf.json / Cargo.toml / package.json 三处版本号一致
  |
  +-- build-windows (windows-latest)    [并行]
  |   |-- 注入 bridge_admin.json（从 Secret）
  |   |-- npm ci
  |   |-- tauri-apps/tauri-action (签名 + 发布)
  |   +-- 创建便携 ZIP 并上传到 Release
  |
  +-- build-macos (macos-latest)        [并行]
      |-- 注入 bridge_admin.json（从 Secret）
      |-- npm ci
      +-- tauri-apps/tauri-action --target universal-apple-darwin (签名 + 发布)
```

Secrets:
- `GITHUB_TOKEN`: Release 发布权限
- `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: 更新签名
- `BRIDGE_ADMIN_JSON`: Bridge 管理后台配置

### 7.4 构建产物

| 平台 | 产物 | 说明 |
|------|------|------|
| Windows | `Mobot Launcher_x.x.x_x64-setup.exe` | NSIS 安装程序 |
| Windows | `Mobot-Launcher_x.x.x_x64_portable.zip` | 便携版（含 `.portable` 标记） |
| macOS | `Mobot Launcher_x.x.x_universal.dmg` | Universal Binary 磁盘映像 |
| macOS | `Mobot Launcher.app.tar.gz` | 应用包压缩文件 |
| 全平台 | `latest.json` | 自动更新端点（含签名） |

Windows NSIS 安装器特性：
- 内嵌 WebView2 Bootstrapper（`embedBootstrapper`）
- 自定义安装钩子（`windows/hooks.nsh`）

macOS 特性：
- Universal Binary（`aarch64-apple-darwin` + `x86_64-apple-darwin`）
- 最低系统版本: macOS 10.13 (High Sierra)
- 启动时自动清理旧版 "Claude Code Launcher.app"

### 7.5 lib.rs 初始化逻辑

应用启动时 `lib.rs` 执行以下操作：

1. 清除 `CLAUDECODE` 环境变量（防止子进程认为在嵌套 Claude Code 会话中）
2. 设置 `NO_PROXY=127.0.0.1,localhost`（WebView2 代理绕过）
3. 注册 Tauri 插件: opener, dialog, clipboard, process, updater
4. macOS: 清理旧版应用包（重命名迁移）
5. 注册 70+ Tauri Commands
6. `RunEvent::Exit`: 调用 `BridgeManager::stop_all()` 清理子进程

---

**文档维护**: 本文档基于项目 v1.0.4 实际代码生成，如有问题请查看源码或联系开发团队。
