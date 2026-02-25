# Claude Code 启动器

一个用于管理和启动 Claude Code 项目的桌面应用程序，基于 Tauri + React + TypeScript 构建。

## 功能特性

### 项目管理
- **多项目支持**：创建和管理多个项目配置
- **默认项目**：系统自带一个默认项目，使用用户主目录作为工作目录
- **项目配置**：每个项目可独立配置启动模式、代理、模型等参数

### 拖拽排序与置顶
- **拖拽排序**：通过拖拽调整项目在列表中的顺序
- **置顶功能**：在编辑页面可将项目设为置顶，置顶项目显示在默认项目之后、普通项目之前
- **排序优先级**：
  1. 默认项目 - 固定第一位，不可拖拽
  2. 置顶项目 - 按置顶时间倒序排列，可在置顶区域内拖拽互换
  3. 普通项目 - 按自定义顺序排列，可在普通区域内拖拽互换

### 启动模式
- **Claude 原版模式**：使用 Anthropic 官方服务，支持配置代理
- **自定义模型模式**：支持配置自定义 API 端点、模型名称和认证令牌
- **远程桥接模式 (Mobot)**：通过 Python Bridge 连接远程服务，支持企业级功能
- **dangerously-skip 模式**：跳过权限确认提示，适合自动化场景

### 远程桥接 (Mobot)
- **Python Agent Server**：基于 FastAPI + Claude Agent SDK，支持多用户会话、安全钩子、技能系统
- **Bridge Client**：WebSocket 长连接到远程 Bridge Server，自动重连和心跳
- **模型配置**：支持原版 Claude (OAuth) 和自定义模型 (API 代理) 两种模式
- **Agent 配置管理**：可视化管理 soul.md、system_prompt.md、MCP 配置、技能目录等
- **自动环境初始化**：首次启动自动创建 venv、安装依赖、初始化配置目录
- **代理隔离**：代理仅传递给 Claude CLI 子进程，不影响 Agent Server 内部通信

### 新手引导
- **首次使用引导**：首次打开应用时自动显示分步引导
- **功能高亮**：逐步高亮关键功能区域，介绍应用功能
- **随时查看**：右下角帮助按钮可随时重新查看引导

### 自动更新
- **启动检查**：应用启动后自动检测新版本
- **一键更新**：发现新版本时顶部横幅提示，点击即可下载安装
- **下载进度**：显示实时下载进度条
- **自动重启**：安装完成后自动重启到新版本

### 其他功能
- **依赖检测**：自动检测 Node.js、Python、Claude CLI、Git Bash 等依赖
- **一键安装**：支持一键安装/更新缺失的依赖
- **命令复制**：生成并复制 PowerShell/CMD/Bash 启动命令
- **文件夹拖拽**：拖拽文件夹到窗口快速创建项目

## 技术栈

- **前端**：React 19 + TypeScript + Tailwind CSS
- **后端**：Rust + Tauri 2 + Python (Bridge)
- **拖拽库**：@dnd-kit
- **剪贴板**：@tauri-apps/plugin-clipboard-manager (macOS 必需)
- **自动更新**：@tauri-apps/plugin-updater + GitHub Releases

## 安装

### macOS (Apple Silicon)

一键安装：

```bash
curl -fsSL https://raw.githubusercontent.com/Earthling18/claude-code-launcher/master/install.sh | bash
```

### Windows

从 [Releases](https://github.com/Earthling18/claude-code-launcher/releases) 下载 `.exe` 安装包。

## 开发

### 环境要求
- Node.js 18+
- Rust 1.70+
- Python 3.10+（远程桥接模式）
- pnpm 或 npm

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run tauri:dev
```

### 构建

```bash
npm run tauri:build
```

构建产物位于 `src-tauri/target/release/bundle/` 目录。

## 配置文件

### 应用配置
- Windows: `%APPDATA%\ClaudeCodeLauncher\config.json`
- macOS: `~/Library/Application Support/ClaudeCodeLauncher/config.json`
- Linux: `~/.config/ClaudeCodeLauncher/config.json`

### Agent 数据目录（远程桥接模式）
- Windows: `%APPDATA%\claude-launcher\agent\`
- macOS/Linux: `~/.config/claude-launcher/agent/`

```
agent/
├── .env                    # 主配置（认证模式、模型、代理等）
├── .mcp.json               # MCP 服务器配置
├── CLAUDE.md               # 项目说明（SDK 自动加载）
├── allowed_tools.txt       # 额外允许的工具列表
├── app/
│   ├── soul.md             # 身份人格
│   └── system_prompt.md    # 系统提示
├── .claude/skills/         # 技能目录
├── venv/                   # Python 虚拟环境（自动创建）
├── workspace/              # 工作目录
└── logs/                   # 日志目录
```

## 平台支持

| 功能 | Windows | macOS |
|------|---------|-------|
| 依赖检测 | ✅ | ✅ (扩展 PATH) |
| 启动 Claude | ✅ PowerShell | ✅ Terminal.app |
| 复制命令 | ✅ | ✅ (Tauri 剪贴板 API) |
| 安装/更新 | ✅ winget | ✅ brew/npm |
| 自动更新 | ✅ NSIS | ✅ DMG |

### macOS 特殊处理

macOS GUI 应用不继承 shell 的 PATH 环境变量，因此：
- **依赖检测**：自动扫描常见安装路径（Homebrew、nvm、pnpm、Volta 等）
- **启动功能**：通过 Terminal.app 启动，Terminal 会加载完整 PATH
- **剪贴板**：使用 Tauri 剪贴板插件，而非浏览器 API

## 发版流程

1. **同步修改三处版本号**（必须一致，CI 会校验）：
   - `src-tauri/tauri.conf.json` — Tauri 配置 & updater latest.json 的版本来源
   - `src-tauri/Cargo.toml` — Rust 编译嵌入 exe 的版本号
   - `package.json` — 前端包版本
2. 提交并打 tag：`git tag v版本号 && git push origin master --tags`
3. GitHub Actions 自动构建、签名、生成更新文件，创建 Draft Release
4. 在 [Releases 页面](https://github.com/Earthling18/claude-code-launcher/releases) 点击 Publish 发布
5. 已安装的旧版应用下次启动时自动收到更新通知

> **注意**：三处版本号不一致会导致更新死循环（exe 嵌入版本来自 Cargo.toml，updater 比对版本来自 tauri.conf.json）。CI 的 `check-version` job 会在构建前自动校验，不一致则阻止构建。

### 自动更新机制

- **更新端点**：GitHub Releases 的 `latest.json`
- **Windows 安装模式**：`basicUi`（显示安装界面，支持自定义安装路径原地更新）
- **签名验证**：使用 minisign 公钥校验安装包完整性

## 许可证

MIT
