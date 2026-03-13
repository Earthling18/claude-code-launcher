# Mobot Launcher - 前端开发指南

> **项目版本**: 1.0.4
> **最后更新**: 2026-03-13
> **技术栈**: React 19 + TypeScript + Tailwind CSS + Vite 7

---

## 目录

- [1. 技术栈概述](#1-技术栈概述)
- [2. 项目结构](#2-项目结构)
- [3. 路由系统](#3-路由系统)
- [4. 页面组件](#4-页面组件)
- [5. 通用组件](#5-通用组件)
- [6. Hooks](#6-hooks)
- [7. API 层](#7-api-层)
- [8. 类型系统](#8-类型系统)
- [9. 样式系统](#9-样式系统)
- [10. 状态管理](#10-状态管理)
- [11. 依赖列表](#11-依赖列表)

---

## 1. 技术栈概述

| 技术 | 版本 | 用途 |
|------|------|------|
| React | ^19.1.0 | UI 框架 |
| TypeScript | ~5.8.3 | 类型安全 |
| Vite | ^7.0.4 | 构建工具，端口 1420，HMR 端口 1421 |
| Tailwind CSS | ^3.4.0 | 原子化 CSS |
| React Router DOM | ^7.13.0 | 客户端路由 |
| @dnd-kit/core | ^6.3.1 | 拖拽排序核心 |
| @dnd-kit/sortable | ^10.0.0 | 列表排序插件 |
| @tauri-apps/api | ^2.10.1 | Tauri 前端 API (invoke, event, window) |
| @tauri-apps/plugin-clipboard-manager | ^2.3.2 | 剪贴板读写 |
| @tauri-apps/plugin-opener | ^2 | 打开 URL/文件 |
| @tauri-apps/plugin-process | ^2 | 应用重启 (relaunch) |
| @tauri-apps/plugin-updater | ^2 | 应用自动更新 |

**编译目标**: ES2020，React JSX 转换，Bundler 模块解析。严格模式开启 (`strict: true`)，禁止未使用的局部变量和参数。

---

## 2. 项目结构

```
src/
├── main.tsx                          # 应用入口，ReactDOM.createRoot + StrictMode
├── App.tsx                           # 主应用组件，BrowserRouter + DragContext + 路由定义
├── api.ts                            # 所有 Tauri invoke 调用的封装 (7 个 API 对象)
├── types.ts                          # 全局类型 (DependencyStatus, AppConfig, MODEL_OPTIONS)
├── index.css                         # Tailwind 指令 + 自定义全局样式
├── types/
│   └── project.ts                    # 项目相关类型 (Project, ProjectConfig, Mobot, CC Config)
├── hooks/
│   └── useUpdateChecker.ts           # 自动更新检测 Hook (installer + portable 双模式)
├── pages/
│   ├── ModeSelectPage.tsx            # 首页 - 本地/远程 模式选择
│   ├── ProjectListPage.tsx           # 项目列表 - 拖拽排序 + 依赖检测 + 首次安装向导
│   ├── ProjectCreatePage.tsx         # 新建项目 - 支持拖拽文件夹创建
│   ├── ProjectDetailPage.tsx         # 项目详情 - 查看配置 + 启动 + 复制命令
│   ├── ProjectEditPage.tsx           # 编辑项目 - 修改配置 + 删除 + 拖拽更新目录
│   └── RemoteBridgePage.tsx          # 远程 Mobot Bridge - 安装/启动/iframe 嵌入
└── components/
    ├── ModeSwitch.tsx                # 本地/远程 切换按钮 (自动最大化/还原窗口)
    ├── ProjectCard.tsx               # 项目卡片 (名称/目录/模式标签/启动/复制命令)
    ├── SortableProjectCard.tsx       # 可拖拽的项目卡片 (useSortable 包装)
    ├── ProjectForm.tsx               # 项目表单 (名称/目录/模式/代理/启动模式/置顶)
    ├── DirectoryPicker.tsx           # 目录选择器 (文本输入 + 系统目录选择对话框)
    ├── ConfigPanel.tsx               # 配置参数面板 (legacy，用于独立配置页)
    ├── ConfirmDialog.tsx             # 确认对话框 (模态遮罩 + danger/default 变体)
    ├── DependencyFrame.tsx           # 依赖检测面板 (折叠/展开/CC配置检测 三态)
    ├── CcConfigPanel.tsx             # CC 配置检测面板 (冲突扫描/BOM修复/MCP迁移)
    ├── LocalSetupWizard.tsx          # 本地首次安装向导 (Node.js/Git/Claude/Codex)
    ├── MobotSetupWizard.tsx          # Mobot Bridge 安装向导 (释放/Python/依赖/启动)
    ├── OnboardingOverlay.tsx         # 新手引导遮罩 (6步聚光灯引导)
    ├── OnboardingTrigger.tsx         # 新手引导触发按钮 (右下角问号图标)
    └── UpdateNotification.tsx        # 更新通知条 (available/downloading/error 三态)
```

---

## 3. 路由系统

使用 `react-router-dom` v7 的 `BrowserRouter` + `Routes` + `Route`。路由定义在 `App.tsx` 的 `AppContent` 组件中。

| 路径 | 页面组件 | 说明 |
|------|----------|------|
| `/` | `ModeSelectPage` | 首页，选择本地或远程模式 |
| `/local` | `ProjectListPage` | 本地项目列表，含首次安装向导 |
| `/local/project/new` | `ProjectCreatePage` | 新建项目 |
| `/local/project/:id` | `ProjectDetailPage` | 项目详情 |
| `/local/project/:id/edit` | `ProjectEditPage` | 编辑项目 |
| `/remote` | `RemoteBridgePage` | 远程 Mobot Bridge 管理 |

**全局包装层** (`AppContent`):
- `DragContext.Provider` — 全局拖拽上下文
- `UpdateNotification` — 顶部更新通知条
- 拖拽遮罩层 — 当文件拖入窗口时显示蓝色虚线框
- `OnboardingOverlay` — 仅在 `/local` 路径显示
- `OnboardingTrigger` — 右下角帮助按钮，始终可见

---

## 4. 页面组件

### 4.1 ModeSelectPage

**文件**: `src/pages/ModeSelectPage.tsx`

首页，两个大按钮选择"本地使用"或"Mobot (远程连接)"。

- **本地使用**: 导航到 `/local`
- **远程连接**: 导航到 `/remote`，并调用 `getCurrentWindow().maximize()` 最大化窗口
- 无 API 调用，无状态管理

### 4.2 ProjectListPage

**文件**: `src/pages/ProjectListPage.tsx`

项目列表页，是本地模式的主页面。

**关键状态**:
| 状态 | 类型 | 说明 |
|------|------|------|
| `depsReady` | `boolean` | 依赖是否就绪，初始值从 `localStorage('local_deps_ok')` 读取 |
| `projects` | `Project[]` | 项目列表 |
| `platform` | `string` | 操作系统平台 |
| `loading` | `boolean` | 加载状态 |
| `activeId` | `string \| null` | 当前拖拽的项目 ID |

**API 调用**:
- `projectApi.getAll()` — 加载项目列表
- `api.getPlatform()` — 获取平台信息
- `projectApi.launch(id)` — 启动项目
- `projectApi.updateProjectsOrder(orders)` — 保存普通项目排序
- `projectApi.updatePinnedOrder(orders)` — 保存置顶项目排序

**核心逻辑**:
- `depsReady === false` 时显示 `LocalSetupWizard`，完成后切换到项目列表
- 项目按规则排序: 默认项目 > 置顶项目 (pinned_at 降序) > 普通项目 (sort_order 升序)
- 使用 `@dnd-kit` 实现拖拽排序，默认项目不可拖拽，置顶组和普通组不可跨组拖拽
- 拖拽使用乐观更新，失败时回滚重新加载
- `PointerSensor` 需 8px 移动距离才触发拖拽（避免误触）
- 项目列表使用 `grid grid-cols-2` 两列布局

**子组件**:
- `ModeSwitch` (active="local")
- `DependencyFrame` (项目列表上方的依赖检测栏)
- `ProjectCard` / `SortableProjectCard` (项目卡片)
- `LocalSetupWizard` (首次安装时)

### 4.3 ProjectCreatePage

**文件**: `src/pages/ProjectCreatePage.tsx`

新建项目页面。

**关键状态**:
| 状态 | 类型 | 说明 |
|------|------|------|
| `saving` | `boolean` | 保存中 |
| `defaultWorkingDirectory` | `string` | 默认工作目录 |
| `lastConfig` | `ProjectConfig \| undefined` | 上一个项目的配置 (作为新项目默认值) |

**API 调用**:
- `systemApi.getHomeDirectory()` — 获取用户主目录作为默认工作目录
- `projectApi.getAll()` — 加载最后一个项目的配置作为模板
- `projectApi.create(name, workingDirectory, config)` — 创建项目
- `projectApi.togglePinned(id, true)` — 置顶新项目 (如勾选)

**拖拽集成**: 从 `DragContext` 读取 `droppedPath`，如果有拖拽路径则作为默认工作目录，消费后清除。

### 4.4 ProjectDetailPage

**文件**: `src/pages/ProjectDetailPage.tsx`

项目详情页，显示项目配置信息、启动按钮和命令复制。

**关键状态**:
| 状态 | 类型 | 说明 |
|------|------|------|
| `project` | `Project \| null` | 当前项目 |
| `copySuccess` | `boolean` | 复制成功提示 (2秒自动消失) |
| `platform` | `string` | 操作系统 |

**API 调用**:
- `projectApi.get(id)` — 加载项目详情
- `api.getPlatform()` — 获取平台
- `projectApi.launch(id)` — 启动项目
- `projectApi.generatePowershellCommand(id)` — 生成 PowerShell 命令
- `projectApi.generateCmdCommand(id)` — 生成 CMD 命令
- `projectApi.generateBashCommand(id)` — 生成 Bash 命令

**平台适配**: Windows 显示 PowerShell + CMD 复制按钮，macOS/Linux 显示 Bash/Zsh 按钮。

### 4.5 ProjectEditPage

**文件**: `src/pages/ProjectEditPage.tsx`

编辑项目页面，含删除功能。

**关键状态**:
| 状态 | 类型 | 说明 |
|------|------|------|
| `project` | `Project \| null` | 当前项目 |
| `saving` | `boolean` | 保存中 |
| `showDeleteConfirm` | `boolean` | 删除确认对话框 |
| `droppedWorkingDirectory` | `string \| null` | 拖拽更新的工作目录 |

**API 调用**:
- `projectApi.get(id)` — 加载项目
- `projectApi.update(id, name, workingDirectory, config, isPinned)` — 更新项目
- `projectApi.delete(id)` — 删除项目

**拖拽集成**: 注册自定义拖拽处理器 (`registerDragHandler`)，将拖入的文件夹路径更新到工作目录字段。默认项目不处理拖拽。使用 `useRef` 保证 handler 引用稳定，避免频繁注册/注销。

**默认项目限制**: `is_default` 为 true 时，名称和工作目录不可修改，不显示删除按钮。

### 4.6 RemoteBridgePage

**文件**: `src/pages/RemoteBridgePage.tsx`

远程 Mobot Bridge 管理页面，四种视图状态:

| ViewState | 说明 |
|-----------|------|
| `loading` | 检测安装状态中 |
| `not_installed` | 未安装，显示 `MobotSetupWizard` |
| `installed_stopped` | 已安装但未运行，自动启动或显示错误 |
| `running` | 运行中，嵌入 iframe 显示配置界面 |

**关键状态**:
| 状态 | 类型 | 说明 |
|------|------|------|
| `viewState` | `ViewState` | 当前视图状态 |
| `status` | `MobotServiceStatus \| null` | 服务状态 |
| `bridgePath` | `string` | 安装路径 |
| `pythonPath` | `string` | Python 路径 |
| `port` | `number` | 固定 8000 |
| `logs` | `string[]` | 服务日志 |
| `showLogs` | `boolean` | 是否显示日志面板 |
| `iframeLoaded` | `boolean` | iframe 是否加载完成 |

**API 调用**:
- `mobotApi.detectInstallation()` — 检测安装状态
- `mobotApi.detectPython()` — 检测 Python
- `mobotApi.startService(path, python, port)` — 启动服务
- `mobotApi.getStatus(port)` — 轮询服务状态 (每 3 秒)
- `mobotApi.checkHealth(port)` — 健康检查
- `mobotApi.isUpdating()` — 检查是否正在热更新
- `mobotApi.getLogs(maxLines)` — 获取日志 (显示日志时每 2 秒轮询)

**自动恢复机制**:
- 服务停止后有 15 秒 (5 次 x 3 秒) 的宽限期等待热更新重启
- 宽限期后尝试自动重启，10 秒冷却防止快速循环
- iframe 挂载后 1.5 秒自动消除加载遮罩

**进入时自动最大化窗口** (`getCurrentWindow().maximize()`)。

---

## 5. 通用组件

### 5.1 ModeSwitch

**文件**: `src/components/ModeSwitch.tsx`

本地/远程模式切换按钮，显示在页面顶部标题栏。

| Prop | 类型 | 说明 |
|------|------|------|
| `active` | `'local' \| 'remote'` | 当前激活模式 |
| `disabled` | `boolean` | 可选，禁用状态 |

切换到远程时最大化窗口，切换到本地时还原窗口。

### 5.2 ProjectCard

**文件**: `src/components/ProjectCard.tsx`

项目卡片，显示项目名称、模式标签、置顶标签、工作目录、时间、启动/复制按钮。

| Prop | 类型 | 说明 |
|------|------|------|
| `project` | `Project` | 项目数据 |
| `platform` | `string` | 操作系统 |
| `onLaunch` | `(id: string) => void` | 启动回调 |
| `onEdit` | `(id: string) => void` | 编辑回调 |
| `isDragging` | `boolean` | 可选，拖拽视觉状态 |

使用 `@tauri-apps/plugin-clipboard-manager` 的 `writeText` 复制命令。路径超过 40 字符时自动缩写 (`C:\...\last\two`)。Windows 显示"复制PS"+"复制CMD"按钮，其他平台显示"复制Bash"按钮。

### 5.3 SortableProjectCard

**文件**: `src/components/SortableProjectCard.tsx`

使用 `@dnd-kit/sortable` 的 `useSortable` 包装 `ProjectCard`，添加拖拽手柄和变换动画。

| Prop | 类型 | 说明 |
|------|------|------|
| `project` | `Project` | 项目数据 |
| `platform` | `string` | 操作系统 |
| `onLaunch` | `(id: string) => void` | 启动回调 |
| `onEdit` | `(id: string) => void` | 编辑回调 |

拖拽时 opacity 降为 0.5。

### 5.4 ProjectForm

**文件**: `src/components/ProjectForm.tsx`

项目创建/编辑的通用表单，被 `ProjectCreatePage` 和 `ProjectEditPage` 共用。

| Prop | 类型 | 说明 |
|------|------|------|
| `initialName` | `string` | 可选，初始项目名称 |
| `initialWorkingDirectory` | `string` | 可选，初始工作目录 |
| `initialConfig` | `ProjectConfig` | 可选，初始配置 |
| `initialIsPinned` | `boolean` | 可选，初始置顶状态 |
| `onSubmit` | `(name, workingDirectory, config, isPinned) => void` | 提交回调 |
| `onCancel` | `() => void` | 取消回调 |
| `onDelete` | `() => void` | 可选，删除回调 (有值时显示删除按钮) |
| `submitLabel` | `string` | 可选，提交按钮文本 |
| `isDefault` | `boolean` | 可选，是否默认项目 (禁用名称和目录编辑) |

**表单字段**:
- 项目名称 (必填)
- 工作目录 (必填，使用 `DirectoryPicker`)
- 配置模式: `claude` / `codex` / `custom` 三选一
  - Claude 账号: 代理地址 (可选)
  - Codex 账号: 代理地址 (可选)
  - 自定义模型: CLI 工具选择 (claude/codex，codex 暂不支持)、Model Name、Base URL、Auth Token
- 启动模式: 普通模式 / 跳过确认模式
- 置顶设置 (非默认项目时显示)

**验证规则**: 项目名称和工作目录必填，代理地址和 Base URL 必须以 `http://` 或 `https://` 开头。

**响应外部变化**: 通过 `useEffect` 监听 `initialWorkingDirectory`、`initialConfig`、`initialIsPinned` 的变化并同步到内部状态 (支持异步加载和拖拽更新)。

### 5.5 DirectoryPicker

**文件**: `src/components/DirectoryPicker.tsx`

文本输入 + "选择或拖入"按钮的目录选择器。

| Prop | 类型 | 说明 |
|------|------|------|
| `value` | `string` | 当前路径 |
| `onChange` | `(value: string) => void` | 路径变更回调 |
| `placeholder` | `string` | 可选，占位文本 |
| `disabled` | `boolean` | 可选，禁用状态 |

点击按钮调用 `dialogApi.selectDirectory()` 打开系统目录选择对话框。

### 5.6 ConfirmDialog

**文件**: `src/components/ConfirmDialog.tsx`

模态确认对话框，支持 `danger` 和 `default` 两种变体。

| Prop | 类型 | 说明 |
|------|------|------|
| `isOpen` | `boolean` | 是否显示 |
| `title` | `string` | 标题 |
| `message` | `string` | 内容 (支持 `\n` 换行) |
| `confirmLabel` | `string` | 可选，确认按钮文本 |
| `cancelLabel` | `string` | 可选，取消按钮文本 |
| `onConfirm` | `() => void` | 确认回调 |
| `onCancel` | `() => void` | 取消回调 |
| `variant` | `'danger' \| 'default'` | 可选，按钮风格 |

点击背景遮罩触发 `onCancel`。

### 5.7 ConfigPanel

**文件**: `src/components/ConfigPanel.tsx`

独立的配置参数面板，用于无项目上下文时的配置管理 (legacy 组件)。

接收完整的配置状态和回调 Props (mode, proxy, model, baseUrl, token, skipPermissions, codexProxy, customCli) 以及启动和复制命令的回调。内部仅管理 `showToken` 状态。

### 5.8 DependencyFrame

**文件**: `src/components/DependencyFrame.tsx`

依赖检测面板，三种显示状态:

| 状态 | 显示 |
|------|------|
| 折叠 | 一行状态栏: 依赖就绪/有更新 + 各依赖版本 + "检查更新"/"CC修复"按钮 |
| 展开 | 详细面板: 每个依赖的安装/更新按钮 |
| CC配置 | `CcConfigPanel` 配置冲突检测面板 |

| Prop | 类型 | 说明 |
|------|------|------|
| `projects` | `Project[]` | 可选，项目列表 (传给 CC 配置检测) |
| `platform` | `string` | 可选，操作系统 |

**检测的依赖**: Node.js、Git、Claude Code、Codex

**行为逻辑**:
- 挂载时并行静默检测四个依赖，结果缓存到 `sessionStorage`
- 有依赖未安装时自动展开面板
- "检查更新"按钮刷新 PATH 后使用 WithUpdate 版 API 重新检测
- 安装/更新后延迟 2 秒再重新检测

### 5.9 CcConfigPanel

**文件**: `src/components/CcConfigPanel.tsx`

CC (Claude Code) 配置检测面板，扫描并修复配置问题。

| Prop | 类型 | 说明 |
|------|------|------|
| `projects` | `Project[]` | 项目列表 |
| `platform` | `string` | 操作系统 |
| `onClose` | `() => void` | 关闭回调 |

**检测内容**:
1. **配置冲突** — 环境变量 / Shell 配置 / settings.json 中的冲突项 (按来源分组显示)
2. **JSON BOM 问题** — UTF-8 BOM 导致配置不生效
3. **MCP 位置问题** — mcpServers 放在 settings.json 而非 .mcp.json

**API 调用**:
- `ccConfigApi.scan(projects)` — 扫描所有配置
- `ccConfigApi.cleanField(filePath, key)` — 清理单个字段
- `ccConfigApi.cleanAll(targets)` — 批量清理
- `ccConfigApi.fixBom(filePath)` — 修复 BOM
- `ccConfigApi.fixMcpMisplaced(filePath, targetPath)` — 迁移 MCP 到 .mcp.json
- `ccConfigApi.removeMcpServers(filePath)` — 移除全局 mcpServers
- `ccConfigApi.openFile(filePath)` — 打开文件

支持"一键修复"批量处理所有可修复的问题。

### 5.10 LocalSetupWizard

**文件**: `src/components/LocalSetupWizard.tsx`

首次使用的本地环境安装向导。

| Prop | 类型 | 说明 |
|------|------|------|
| `onComplete` | `() => void` | 完成回调 |

按顺序安装: Node.js -> Git -> Claude Code -> Codex。每一步先检测是否已安装，已安装则跳过。未安装时打开安装程序并轮询等待安装完成 (每 3 秒检查，最多 60 次)。

完成后写入 `localStorage('local_deps_ok', '1')`。失败时显示"重试"和"跳过"按钮。

### 5.11 MobotSetupWizard

**文件**: `src/components/MobotSetupWizard.tsx`

Mobot Bridge 安装向导，四步流程。

| Prop | 类型 | 说明 |
|------|------|------|
| `onComplete` | `(bridgePath: string, pythonPath: string) => void` | 完成回调 |
| `onCancel` | `() => void` | 取消回调 |

**步骤**:
1. 释放 mobot-bridge — `mobotApi.install()`
2. 检测 Python — `mobotApi.detectPython()`
3. 安装依赖 — `mobotApi.installDeps(path, python)`，监听 `mobot-deps-progress` 事件实时显示进度
4. 启动服务 — `mobotApi.startService(path, python, 8000)`，轮询健康检查 (最多 15 次，每次 2 秒)

底部显示实时安装日志 (保留最近 50 条)。

### 5.12 OnboardingOverlay

**文件**: `src/components/OnboardingOverlay.tsx`

新手引导遮罩，6 步聚光灯引导。

| Prop | 类型 | 说明 |
|------|------|------|
| `onComplete` | `() => void` | 完成/跳过回调 |

**引导步骤**:
1. `welcome` — 欢迎介绍 (居中)
2. `dependencies` — 依赖检测栏 (底部定位)
3. `default-project` — 默认项目卡片 (底部定位)
4. `create` — 新建项目按钮 (底部定位)
5. `launch` — 启动按钮区域 (顶部定位)
6. `finish` — 完成引导 (居中)

通过 `data-onboarding` 属性定位目标元素，使用 CSS `clip-path` 实现聚光灯剪裁效果。工具提示自动保持在视口内。

### 5.13 OnboardingTrigger

**文件**: `src/components/OnboardingTrigger.tsx`

右下角固定定位的问号图标按钮 (32x32)，点击触发新手引导。

| Prop | 类型 | 说明 |
|------|------|------|
| `onClick` | `() => void` | 点击回调 |

### 5.14 UpdateNotification

**文件**: `src/components/UpdateNotification.tsx`

顶部更新通知条。

| Prop | 类型 | 说明 |
|------|------|------|
| `status` | `UpdateStatus` | 更新状态 |
| `version` | `string \| null` | 新版本号 |
| `progress` | `number` | 下载进度 0-100 |
| `error` | `string \| null` | 错误信息 |
| `isPortable` | `boolean` | 是否便携版 |
| `onUpdate` | `() => void` | 更新/下载回调 |
| `onDismiss` | `() => void` | 关闭回调 |
| `onRetry` | `() => void` | 重试回调 |

三种显示状态:
- `available`: 显示版本号 + "稍后再说" + "立即更新"/"前往下载" (portable)
- `downloading`: 显示进度条
- `error`: 显示错误 + "关闭" + "重试"
- `idle`/`checking`: 不渲染

---

## 6. Hooks

### 6.1 useUpdateChecker

**文件**: `src/hooks/useUpdateChecker.ts`

自动更新检测 Hook，3 秒延迟后检查更新。

**返回值**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `status` | `'idle' \| 'checking' \| 'available' \| 'downloading' \| 'error'` | 更新状态 |
| `version` | `string \| null` | 新版本号 |
| `progress` | `number` | 下载进度 |
| `error` | `string \| null` | 错误信息 |
| `isPortable` | `boolean` | 是否便携版 |
| `downloadAndInstall` | `() => Promise<void>` | 执行更新 |
| `dismiss` | `() => void` | 关闭通知 |
| `retry` | `() => void` | 重试更新 |

**双模式更新**:
- **Installer 模式**: 使用 Tauri 内置 updater (`@tauri-apps/plugin-updater`)，下载后自动 `relaunch()`
- **Portable 模式**: 手动从 GitHub 的 `latest.json` 获取版本，有更新时打开浏览器下载页

通过 `invoke('is_portable_mode')` 判断模式。使用 `compareSemver()` 函数比较语义版本号。

---

## 7. API 层

**文件**: `src/api.ts`

所有 API 通过 Tauri 的 `invoke()` 调用 Rust 后端命令。共 7 个 API 对象:

### 7.1 api — 通用 API

```typescript
export const api = {
  // 依赖检测 (6 个，含 WithUpdate 版)
  checkNodejs, checkClaude, checkGitbash,
  checkNodejsWithUpdate, checkClaudeWithUpdate, checkGitbashWithUpdate,
  checkCodex, checkCodexWithUpdate,
  refreshSystemPath,

  // 安装/更新 (8 个)
  installNodejs, updateNodejs, installClaude, updateClaude,
  installGitbash, updateGitbash, installCodex, updateCodex,

  // 启动
  launchClaudeCode(config: Record<string, string>),

  // 命令生成
  generatePowershellCommand, generateCmdCommand, generateBashCommand,

  // 平台
  getPlatform() => string,

  // 设置管理
  saveToSettings, resetSettings, openSettingsFile,

  // 应用配置 (legacy)
  saveAppConfig(config: AppConfig), loadAppConfig() => AppConfig,
};
```

### 7.2 projectApi — 项目管理

```typescript
export const projectApi = {
  getAll() => Project[],
  get(id) => Project,
  create(name, workingDirectory, config) => Project,
  update(id, name?, workingDirectory?, config?, isPinned?) => Project,
  delete(id) => void,
  launch(id) => void,
  generatePowershellCommand(id) => string,
  generateCmdCommand(id) => string,
  generateBashCommand(id) => string,
  updateProjectsOrder(orders: ProjectOrderItem[]) => void,
  updatePinnedOrder(orders: PinnedOrderItem[]) => void,
  togglePinned(id, isPinned) => Project,
};
```

### 7.3 mobotApi — Mobot Bridge 管理

```typescript
export const mobotApi = {
  detectInstallation() => InstallStatus,
  install() => string,                     // 返回安装路径
  detectPython() => string | null,
  checkDepsInstalled(bridgePath) => boolean,
  installDeps(bridgePath, python) => string, // 返回 python 路径
  startService(bridgePath, python, port) => number, // 返回 PID
  stopService() => void,
  checkHealth(port) => HealthStatus,
  getStatus(port) => MobotServiceStatus,
  getLogs(maxLines?) => string[],
  getHostname() => string,
  getUsername() => string,
  isUpdating() => boolean,
};
```

### 7.4 ccConfigApi — CC 配置检测

```typescript
export const ccConfigApi = {
  scan(projects: {name, working_directory}[]) => ConfigScanResult,
  cleanField(filePath, key) => void,
  cleanAll(targets: {file_path, key}[]) => number,
  openFile(filePath) => void,
  fixBom(filePath) => void,
  fixMcpMisplaced(filePath, targetPath) => void,
  removeMcpServers(filePath) => void,
};
```

### 7.5 claudeLoginApi — Claude 登录检查

```typescript
export const claudeLoginApi = {
  checkLogin() => boolean,
  launchForLogin(proxy?) => void,
};
```

### 7.6 dialogApi — 对话框

```typescript
export const dialogApi = {
  selectDirectory() => string | null,
};
```

### 7.7 systemApi — 系统

```typescript
export const systemApi = {
  getHomeDirectory() => string,
};
```

### 7.8 onboardingApi — 新手引导

```typescript
export const onboardingApi = {
  getStatus() => boolean,        // 是否已完成引导
  setCompleted() => void,
};
```

---

## 8. 类型系统

### 8.1 types.ts — 全局类型

```typescript
// 依赖检测结果
interface DependencyStatus {
  installed: boolean;
  version: string | null;
  meets_requirement: boolean;
  latest_version: string | null;
  update_available: boolean;
  error: string | null;
}

// 应用配置 (legacy，用于 saveAppConfig/loadAppConfig)
interface AppConfig {
  mode: 'claude' | 'custom';
  proxy: string;
  model: string;
  base_url: string;
  token: string;
  skip_permissions: boolean;
}

// 默认应用配置
const DEFAULT_CONFIG: AppConfig = {
  mode: 'claude',
  proxy: '',
  model: 'qwen3-coder-480b-a35b',
  base_url: 'http://litellm.uattest.weoa.com',
  token: '',
  skip_permissions: true,
};

// 模型选项列表
const MODEL_OPTIONS = ['deepseek-v3', 'qwen3-235b-a22b', 'qwen3-coder-480b-a35b'];
```

### 8.2 types/project.ts — 项目类型

```typescript
// 项目配置
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

// 项目实体
interface Project {
  id: string;
  name: string;
  working_directory: string;
  config: ProjectConfig;
  is_default: boolean;
  created_at: number;           // Unix timestamp
  updated_at: number;
  last_launched_at?: number;
  is_pinned: boolean;
  pinned_at?: number;
  sort_order: number;
}

// 排序项
interface ProjectOrderItem { id: string; sort_order: number; }
interface PinnedOrderItem { id: string; pinned_at: number; }

// Mobot 安装状态 (tagged union)
type InstallStatus =
  | 'NotInstalled'
  | { Installed: { path: string } }
  | { Running: { path: string; port: number } };

// 健康检查
interface HealthStatus { healthy: boolean; details: string; }

// Mobot 服务状态
interface MobotServiceStatus {
  installed: boolean;
  running: boolean;
  pid: number | null;
  port: number;
  install_path: string | null;
  healthy: boolean;
  started_at: number | null;
}

// CC 配置检测结果
interface ConfigScanResult {
  conflicts: ConfigConflict[];
  bom_files: BomFileIssue[];
  mcp_misplaced: McpMisplaced[];
}

interface ConfigConflict {
  source: string;               // 'shell_profile' | 'registry_user' | 'registry_system' | 'global' | 'project:xxx'
  file_path: string | null;
  key: string;
  value: string;
  can_clean: boolean;
}

interface BomFileIssue { file_path: string; }

interface McpMisplaced {
  file_path: string;
  target_path: string;
  keys: string[];
  can_fix: boolean;
}

// 默认项目配置
const DEFAULT_PROJECT_CONFIG: ProjectConfig = {
  mode: 'claude',
  proxy: '',
  model: 'qwen3-coder-480b-a35b',
  base_url: 'http://litellm.uattest.weoa.com',
  token: '',
  skip_permissions: true,
  codex_api_key: '',
  custom_cli: 'claude',
  mobot_bridge_path: null,
  mobot_bridge_port: 8000,
};
```

---

## 9. 样式系统

### 9.1 Tailwind 配置

**文件**: `tailwind.config.js`

```javascript
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: '#007ACC',
        'primary-hover': '#005a9e',
        success: '#5a7c5c',
        'success-hover': '#4a6c4c',
        error: '#8b5a5a',
        'error-hover': '#7b4a4a',
        warning: '#FF9800',
        'warning-hover': '#e68900',
      },
      fontFamily: {
        sans: ['Microsoft YaHei', 'sans-serif'],
      },
    },
  },
  darkMode: 'class',
};
```

### 9.2 全局样式 (index.css)

**基础设置**:
- 字体: Microsoft YaHei
- 背景: `#212121` (深灰)
- 前景: `#DCE4EE` (浅蓝灰)
- 全局 `box-sizing: border-box`

**自定义 CSS 类**:

| 类名 | 用途 |
|------|------|
| `.card-frame` | 卡片容器：渐变背景 (#2B2B2B -> #252525)、12px 圆角、阴影 |
| `.btn-primary` | 主按钮：蓝色背景 (#3b82f6)、悬停上移 1px + 蓝色阴影 |
| `.btn-secondary` | 次要按钮：灰色背景 (#565B5E) |
| `.dropdown-menu` | 下拉菜单动画：从上方滑入 (slideDown) |

**自定义滚动条**: 宽 8px，轨道 #2B2B2B，滑块 #565B5E (hover: #7A8488)，圆角 4px。

**输入框聚焦**: 蓝色边框 (#3b82f6) + 蓝色光晕 (box-shadow)。

### 9.3 常用内联颜色

项目中大量使用 Tailwind 的 arbitrary values 而非主题色:

| 颜色 | 用途 |
|------|------|
| `#212121` | 页面背景 |
| `#2a2a2a` | 卡片/按钮背景 |
| `#3a3a3a` | 边框 |
| `#3b82f6` | 主要操作蓝色 |
| `#2563eb` | 蓝色 hover |
| `#10b981` | 成功/健康绿色 |
| `#f59e0b` | 置顶标签黄色 |
| `#565B5E` | 次要按钮灰色 |
| `#999999` | 辅助文字 |
| `#DCE4EE` | 主要文字 |

---

## 10. 状态管理

### 10.1 DragContext — 全局拖拽上下文

**定义在**: `App.tsx`

```typescript
interface DragContextType {
  droppedPath: string | null;
  setDroppedPath: (path: string | null) => void;
  registerDragHandler: (handler: DragHandler) => void;
  unregisterDragHandler: (handler: DragHandler) => void;
}
```

- **droppedPath**: 拖入窗口的文件夹路径。默认行为是导航到 `/local/project/new` 并传递路径创建新项目。
- **registerDragHandler**: 注册自定义处理器，返回 `true` 表示已处理 (阻止默认行为)。`ProjectEditPage` 用此机制将拖入的路径更新到工作目录。
- 拖拽事件通过 Tauri 的 `tauri://drag-drop` 事件获取文件路径。

### 10.2 组件状态模式

**无全局状态库**。各页面独立管理自身状态，通过 URL 参数 (`useParams`) 和导航 (`useNavigate`) 传递上下文。

**常见模式**:
- 页面挂载时加载数据 (`useEffect` + async)
- 加载/错误/数据三态渲染
- 乐观更新 + 失败回滚 (拖拽排序)
- `sessionStorage` 缓存依赖检测结果
- `localStorage` 持久化首次安装完成标记
- `useRef` 防止 React StrictMode 双重执行 (`hasStarted.current`)
- `useMemo` 缓存排序/分组结果

### 10.3 @dnd-kit 拖拽排序

在 `ProjectListPage` 中:

- `DndContext` 包裹列表，使用 `closestCenter` 碰撞检测
- 置顶项目和普通项目分别用各自的 `SortableContext`
- `DragOverlay` 显示拖拽中的卡片副本
- 拖拽限制: 不可拖拽默认项目，不可跨组拖拽
- 排序持久化: 置顶项目用 `pinned_at` (时间戳)，普通项目用 `sort_order` (索引)

---

## 11. 依赖列表

### 11.1 运行时依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| `react` | ^19.1.0 | UI 框架 |
| `react-dom` | ^19.1.0 | DOM 渲染 |
| `react-router-dom` | ^7.13.0 | 客户端路由 |
| `@dnd-kit/core` | ^6.3.1 | 拖拽核心 |
| `@dnd-kit/sortable` | ^10.0.0 | 列表排序 |
| `@dnd-kit/utilities` | ^3.2.2 | 工具函数 (CSS.Transform) |
| `@tauri-apps/api` | ^2.10.1 | Tauri 核心 API (invoke, event, window, app) |
| `@tauri-apps/plugin-clipboard-manager` | ^2.3.2 | 剪贴板操作 (writeText) |
| `@tauri-apps/plugin-opener` | ^2 | 打开 URL |
| `@tauri-apps/plugin-process` | ^2 | 应用重启 (relaunch) |
| `@tauri-apps/plugin-updater` | ^2 | 应用自动更新 (check, Update) |

### 11.2 开发依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| `@tauri-apps/cli` | ^2.10.0 | Tauri CLI 工具 |
| `@types/react` | ^19.1.8 | React 类型定义 |
| `@types/react-dom` | ^19.1.6 | React DOM 类型定义 |
| `@types/react-router-dom` | ^5.3.3 | React Router 类型定义 |
| `@vitejs/plugin-react` | ^4.6.0 | Vite React 插件 |
| `autoprefixer` | ^10.4.22 | CSS 前缀自动化 |
| `postcss` | ^8.5.6 | CSS 处理器 |
| `tailwindcss` | ^3.4.0 | 原子化 CSS 框架 |
| `typescript` | ~5.8.3 | TypeScript 编译器 |
| `vite` | ^7.0.4 | 构建工具 |

### 11.3 NPM Scripts

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动 Vite 开发服务器 (端口 1420) |
| `npm run build` | TypeScript 编译 + Vite 构建 |
| `npm run preview` | 预览构建产物 |
| `npm run tauri:dev` | 启动 Tauri 开发模式 |
| `npm run tauri:build` | 构建 Tauri 应用 |
| `npm run tauri:build-clean` | 清理后构建 Tauri 应用 |

---

**相关文档**:
- [项目总览](./PROJECT_DOCUMENTATION.md)
- [后端开发指南](./BACKEND_GUIDE.md)
- [API 参考](./API_REFERENCE.md)
