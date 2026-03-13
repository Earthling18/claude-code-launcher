# Mobot Launcher - 开发指南

> **项目版本**: 1.0.4
> **最后更新**: 2026-03-13
> **支持平台**: Windows 10/11, macOS 10.13+

---

## 目录

- [1. 环境准备](#1-环境准备)
- [2. 项目初始化](#2-项目初始化)
- [3. 开发工作流](#3-开发工作流)
- [4. 项目配置](#4-项目配置)
- [5. 资源管理](#5-资源管理)
- [6. CI/CD (GitHub Actions)](#6-cicd-github-actions)
- [7. 发布流程](#7-发布流程)
- [8. NSIS 安装器](#8-nsis-安装器)
- [9. 便携模式](#9-便携模式)
- [10. 调试技巧](#10-调试技巧)
- [11. 常见问题](#11-常见问题)

---

## 1. 环境准备

### 1.1 Node.js 18+

CI 使用 Node.js 20，本地开发 18+ 即可。

**Windows**:
```bash
winget install OpenJS.NodeJS.LTS
```

**macOS**:
从 https://nodejs.org/ 下载 LTS 版本，或使用 Homebrew：
```bash
brew install node@20
```

**验证**:
```bash
node --version   # v20.x.x
npm --version    # 10.x.x
```

### 1.2 Rust (stable)

**Windows / macOS / Linux**:
```bash
# Windows: 下载并运行 https://rustup.rs/ 的 rustup-init.exe
# macOS/Linux:
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

macOS 构建 universal binary 需要额外 target：
```bash
rustup target add aarch64-apple-darwin x86_64-apple-darwin
```

**验证**:
```bash
rustc --version
cargo --version
```

### 1.3 平台特定依赖

**Windows**: 需要 Visual Studio C++ Build Tools。安装时勾选：
- Desktop development with C++
- MSVC v142+
- Windows 10/11 SDK

```bash
winget install Microsoft.VisualStudio.2022.BuildTools
```

**macOS**: 需要 Xcode Command Line Tools：
```bash
xcode-select --install
```

### 1.4 Git

```bash
# Windows
winget install Git.Git

# macOS (xcode-select 已包含 git，或使用 Homebrew)
brew install git
```

---

## 2. 项目初始化

### 2.1 克隆项目

```bash
git clone <repository-url> claude-code-launcher-tauri
cd claude-code-launcher-tauri
```

### 2.2 安装前端依赖

```bash
npm install
```

主要依赖（见 `package.json`）：
- **运行时**: React 19, react-router-dom 7, @dnd-kit/core + sortable, @tauri-apps/api 2, @tauri-apps/plugin-clipboard-manager, @tauri-apps/plugin-opener, @tauri-apps/plugin-process, @tauri-apps/plugin-updater
- **开发时**: @tauri-apps/cli 2, Vite 7, @vitejs/plugin-react, TypeScript 5.8, Tailwind CSS 3.4, PostCSS, Autoprefixer

### 2.3 检查 Rust 依赖

```bash
cd src-tauri
cargo check
cd ..
```

首次运行会下载并编译所有 crate，耗时约 3-5 分钟。主要 Rust 依赖（见 `Cargo.toml`）：
- **Tauri 生态**: tauri 2, tauri-plugin-opener, tauri-plugin-dialog, tauri-plugin-clipboard-manager, tauri-plugin-updater 2.10, tauri-plugin-process 2.3
- **序列化**: serde, serde_json
- **异步/网络**: tokio (full), reqwest 0.12 (json + blocking)
- **工具**: regex, base64 0.22, dirs 5, once_cell, log, zip 2
- **Windows 专用**: winreg 0.52, windows 0.58 (Win32_Foundation, Win32_UI_WindowsAndMessaging, Win32_System_Threading)

---

## 3. 开发工作流

### 3.1 npm scripts

| 命令 | 说明 |
|------|------|
| `npm run tauri:dev` | 启动开发模式（Vite dev server + Rust debug 编译 + 桌面窗口） |
| `npm run tauri:build` | 构建生产版本（前端 build + Rust release 编译 + 打包安装器） |
| `npm run tauri:build-clean` | 清理后重新构建（等同 `tauri build -- --clean`） |
| `npm run dev` | 仅启动 Vite 前端开发服务器（不启动 Tauri） |
| `npm run build` | 仅构建前端（tsc + vite build，输出到 `dist/`） |
| `npm run preview` | 预览前端构建产物 |

> **注意**: 使用带冒号的脚本名 `npm run tauri:dev`，而非 `npm run tauri dev`。

### 3.2 开发模式详情

运行 `npm run tauri:dev` 后的流程：

1. Tauri CLI 执行 `beforeDevCommand`（即 `npm run dev`），启动 Vite 开发服务器
2. Vite 监听 `localhost:1420`（strictPort，端口被占用会直接报错）
3. HMR WebSocket 端口 `1421`（当设置了 `TAURI_DEV_HOST` 环境变量时启用远程 HMR）
4. Rust 代码以 debug 模式编译并启动桌面窗口
5. 前端代码修改后 Vite HMR 即时热更新，无需重启
6. Rust 代码修改后 Cargo 自动重编译并重启应用（约 10-30 秒）
7. Vite 配置了忽略 `**/src-tauri/**` 目录的文件监听，避免 Rust 编译触发前端刷新

### 3.3 构建生产版本

运行 `npm run tauri:build` 后的流程：

1. 执行 `beforeBuildCommand`（即 `npm run build`），TypeScript 编译 + Vite 构建前端到 `dist/`
2. Cargo 以 release 模式编译 Rust 代码
3. 根据平台生成安装包：
   - **Windows**: NSIS 安装器 (`Mobot.Launcher_1.0.4_x64-setup.exe`) + NSIS ZIP
   - **macOS**: `.app` 应用包 + `.dmg` 磁盘映像

构建产物位于 `src-tauri/target/release/bundle/`。

---

## 4. 项目配置

### 4.1 tauri.conf.json

核心 Tauri 配置文件，位于 `src-tauri/tauri.conf.json`：

- **productName**: `Mobot Launcher`
- **identifier**: `com.claudecode.launcher`
- **窗口**: 750x700 默认大小，最小 700x600，可调整大小，居中显示
- **CSP**: 设为 `null`（不限制）
- **bundle targets**: `nsis`（Windows 安装器）、`app`（macOS .app）、`dmg`（macOS 磁盘映像）
- **publisher**: 微众银行
- **resources**: 打包 `resources/bridge/**/*` 到安装目录
- **macOS minimumSystemVersion**: 10.13
- **createUpdaterArtifacts**: `true`，构建时自动生成 updater 签名文件
- **WebView2 安装模式**: `embedBootstrapper`，将 WebView2 引导安装程序嵌入 NSIS 安装器，用户安装时若缺少 WebView2 会自动引导安装
- **NSIS hooks**: `./windows/hooks.nsh`，自定义安装/卸载钩子
- **Updater**: 配置了公钥和 GitHub Releases 端点，Windows 更新使用 `basicUi` 模式（显示 NSIS 安装界面）

### 4.2 vite.config.ts

```typescript
// 关键配置：
server: {
  port: 1420,          // Tauri 期望的固定端口
  strictPort: true,    // 端口被占用时直接报错而非自动换端口
  host: host || false, // 默认仅本地访问，设置 TAURI_DEV_HOST 可暴露
  hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
  watch: {
    ignored: ["**/src-tauri/**"],  // 忽略 Rust 目录变化
  },
}
```

### 4.3 TypeScript 配置

`tsconfig.json` 配置：
- **target**: ES2020
- **module**: ESNext，bundler 模式解析
- **jsx**: react-jsx
- **strict**: true，启用 noUnusedLocals、noUnusedParameters、noFallthroughCasesInSwitch
- **include**: 仅 `src/` 目录

### 4.4 Tailwind CSS 配置

`tailwind.config.js` 配置：
- **content**: `./index.html` + `./src/**/*.{js,ts,jsx,tsx}`
- **darkMode**: `class`
- **自定义颜色**: primary (#007ACC), success (#5a7c5c), error (#8b5a5a), warning (#FF9800) 及各自的 hover 色
- **字体**: Microsoft YaHei 为首选 sans-serif 字体

---

## 5. 资源管理

### 5.1 Bridge 资源打包

`src-tauri/resources/bridge/` 目录下的所有文件随应用打包（通过 `tauri.conf.json` 的 `bundle.resources` 配置）。包含：

- `app/` -- FastAPI Agent 服务代码
- `bridge/` -- WebSocket 桥接客户端
- `defaults/` -- 首次运行的默认配置模板
- `requirements.txt` -- Python 依赖声明
- `bridge_admin.json` -- Admin API 凭据（**gitignored**，CI 通过 `secrets.BRIDGE_ADMIN_JSON` 注入）

### 5.2 MinGit 打包

`src-tauri/resources/bridge/mingit/` 目录包含 MinGit 便携版 Git。

`.gitignore` 中全局排除了 `*.exe`，但通过例外规则允许 MinGit 的可执行文件：
```
*.exe
!src-tauri/resources/bridge/mingit/**/*.exe
```

Rust 后端在运行时设置 MinGit 相关环境变量，确保子进程（claude CLI、bridge agents）能使用打包的 Git。

### 5.3 嵌入式 Python (python-embed/)

`src-tauri/resources/bridge/python-embed/` 包含 Python 3.11 嵌入式发行版（仅 Windows）。

由于 `.gitignore` 排除 `*.exe`，`python.exe` 和 `pythonw.exe` 以 `.bin` 后缀存储在仓库中。运行时 `bridge_manager.rs` 将文件复制到用户数据目录后自动将 `.bin` 重命名回 `.exe`。

**添加新的 .exe 资源时务必使用相同方案**，否则文件不会被 Git 跟踪，CI 构建中将缺失。

### 5.4 Wheel 包 (wheels/)

`src-tauri/resources/bridge/wheels/` 包含预构建的 Python 依赖包（.whl 文件），用于离线安装 Python 依赖，避免用户安装时需要网络连接。

---

## 6. CI/CD (GitHub Actions)

工作流文件：`.github/workflows/build.yml`

### 6.1 触发条件

- **标签推送**: 推送 `v*` 格式的 tag（如 `v1.0.4`）自动触发
- **手动触发**: 支持 `workflow_dispatch`，可在 GitHub Actions 页面手动运行

### 6.2 check-version job

运行于 `ubuntu-latest`，校验三个文件的版本号一致性：

| 文件 | 提取方式 |
|------|----------|
| `src-tauri/tauri.conf.json` | JSON 中的 `version` 字段 |
| `src-tauri/Cargo.toml` | `version = "x.x.x"` |
| `package.json` | JSON 中的 `version` 字段 |

任何一处版本不一致，构建直接失败并报错 `Version mismatch!`。

### 6.3 build-windows job

运行于 `windows-latest`，依赖 `check-version` 通过。

步骤：
1. **checkout** 代码
2. **注入 bridge_admin.json**: 从 `secrets.BRIDGE_ADMIN_JSON` 写入 `src-tauri/resources/bridge/bridge_admin.json`
3. **Setup Node.js 20** + **Setup Rust stable**
4. **npm ci** 安装前端依赖
5. **tauri-apps/tauri-action@v0.5.25** 构建：
   - 使用 `TAURI_SIGNING_PRIVATE_KEY` 和 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` 签名 updater 产物
   - `releaseDraft: true` 创建 Draft Release
   - `updaterJsonPreferNsis: true` updater 的 `latest.json` 优先指向 NSIS 安装器
6. **创建便携版 ZIP**（PowerShell 脚本）：
   - 复制 `target/release/mobot-launcher-tauri.exe` 为 `Mobot Launcher.exe`
   - 复制 `target/release/resources/` 目录
   - 创建 `.portable` 标记文件
   - 压缩为 `Mobot-Launcher_{version}_x64_portable.zip`
7. **上传便携版 ZIP** 到 GitHub Release（使用 `gh release upload --clobber`）

### 6.4 build-macos job

运行于 `macos-latest`，依赖 `check-version` 通过。

步骤与 Windows 类似，区别在于：
- Rust 安装时添加 `aarch64-apple-darwin` 和 `x86_64-apple-darwin` 两个 target
- tauri-action 使用 `args: --target universal-apple-darwin` 构建 universal binary（同时支持 ARM 和 Intel Mac）
- 同样注入 `bridge_admin.json`
- 不构建便携版

### 6.5 Updater 签名

构建时通过环境变量 `TAURI_SIGNING_PRIVATE_KEY` 和 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` 对安装包签名。生成的 `.sig` 文件和 `latest.json` 随 Release 上传，客户端 updater 使用 `tauri.conf.json` 中配置的公钥验证签名。

### 6.6 Release 产物汇总

| 平台 | 产物 |
|------|------|
| Windows | NSIS 安装器 `.exe`、NSIS `.zip`、updater `.sig`、便携版 `_portable.zip` |
| macOS | `.app`（在 `.dmg` 内）、`.dmg`、updater `.sig` |
| 通用 | `latest.json`（updater 端点） |

---

## 7. 发布流程

### 7.1 版本号更新

**三个文件必须同步修改**（CI 会校验一致性）：

| 文件 | 字段 |
|------|------|
| `package.json` | `"version": "x.x.x"` |
| `src-tauri/Cargo.toml` | `version = "x.x.x"` |
| `src-tauri/tauri.conf.json` | `"version": "x.x.x"` |

> 版本不一致的后果：`Cargo.toml` 的版本编译进 exe 文件元数据，`tauri.conf.json` 的版本写入 `latest.json`。两者不一致会导致自动更新死循环 -- exe 报告的版本始终"低于" latest.json 中的版本，每次启动都提示更新。

### 7.2 发布步骤

```bash
# 1. 修改三处版本号
# 2. 提交
git add package.json src-tauri/Cargo.toml src-tauri/tauri.conf.json
git commit -m "release: v1.0.5"

# 3. 打 tag 并推送
git tag v1.0.5
git push origin master --tags
```

### 7.3 CI 自动构建与发布

1. 推送 tag 后，GitHub Actions 自动触发 `Build and Release` 工作流
2. `check-version` 校验版本一致性
3. `build-windows` 和 `build-macos` 并行构建
4. 构建完成后自动创建 **Draft Release**，上传所有产物
5. 前往 GitHub Releases 页面，编辑 Draft Release，补充 Release Notes
6. 点击 **Publish release** 正式发布
7. 已安装的客户端下次启动时通过 updater 端点检测到新版本，提示用户更新

---

## 8. NSIS 安装器

### 8.1 hooks.nsh 迁移钩子

`src-tauri/windows/hooks.nsh` 实现了从旧版 "Claude Code Launcher" 到 "Mobot Launcher" 的自动迁移：

**NSIS_HOOK_PREINSTALL**（安装前）：
- 检查注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher`
- 若找到旧版，读取安装路径，静默运行旧版卸载程序 (`/S`)
- 等待 2 秒后清理残留文件和注册表项
- 删除旧版桌面和开始菜单快捷方式

**NSIS_HOOK_POSTINSTALL**（安装后）：
- 仅在检测到旧版迁移时（`$MigratedFromOld == 1`）创建新快捷方式
- 正常的 Mobot->Mobot 更新不会触发快捷方式创建（尊重用户自定义）

### 8.2 WebView2 embedBootstrapper

`tauri.conf.json` 配置了 `webviewInstallMode: { type: "embedBootstrapper" }`，将 WebView2 Evergreen Bootstrapper 嵌入 NSIS 安装器。安装时若系统缺少 WebView2 Runtime，会自动引导用户下载安装。

### 8.3 createUpdaterArtifacts

`tauri.conf.json` 中 `bundle.createUpdaterArtifacts: true`，构建时自动生成 `.sig` 签名文件和 `latest.json`，供客户端 updater 使用。

---

## 9. 便携模式

### 9.1 工作原理

便携模式通过在可执行文件同级目录放置 `.portable` 标记文件来激活。应用启动时通过 `is_portable_mode` 命令检测该文件是否存在。

便携模式下，应用数据存储在程序目录而非 `%APPDATA%`。

### 9.2 CI 构建便携版

`build-windows` job 的最后一步自动创建便携版 ZIP：

1. 创建 `portable-staging/` 临时目录
2. 复制 `target/release/mobot-launcher-tauri.exe` 为 `Mobot Launcher.exe`
3. 复制 `target/release/resources/` 目录（包含 bridge 资源）
4. 创建 `.portable` 标记文件，内容为 `Mobot Launcher Portable v{version}`
5. 压缩为 `Mobot-Launcher_{version}_x64_portable.zip`
6. 上传到 GitHub Release

### 9.3 本地测试便携模式

构建完成后：
```bash
# 在构建输出目录创建 .portable 标记文件
echo "portable" > src-tauri/target/release/.portable
# 然后直接运行 exe
```

---

## 10. 调试技巧

### 10.1 Rust 日志

项目使用 `log` crate。开发模式下：
```rust
log::info!("信息: {}", variable);
log::warn!("警告: {}", variable);
log::error!("错误: {}", variable);

// 或直接输出到 stderr（开发模式终端可见）
eprintln!("调试信息: {:?}", variable);
```

日志输出在启动 `npm run tauri:dev` 的终端中查看。

### 10.2 前端 DevTools

开发模式下可打开 WebView DevTools：
- Windows: `F12` 或 `Ctrl+Shift+I`
- macOS: `Cmd+Option+I`

功能：Console 日志、Network 查看 IPC 调用、Elements 检查 DOM/样式、Sources 断点调试。

### 10.3 Tauri IPC 调试

```typescript
// 前端调用 Rust 命令
import { invoke } from '@tauri-apps/api/core';

try {
  const result = await invoke('command_name', { param: value });
  console.log('返回:', result);
} catch (error) {
  console.error('失败:', error);
}
```

```rust
// Rust 端日志
#[tauri::command]
pub fn command_name(param: String) -> Result<String, String> {
    eprintln!("收到参数: {}", param);
    // ...
}
```

### 10.4 应用初始化流程

`src-tauri/src/lib.rs` 中的 `run()` 函数：
1. 清除 `CLAUDECODE` 环境变量（防止子进程认为在嵌套 Claude Code 会话中）
2. 设置 `NO_PROXY` 包含 `127.0.0.1,localhost`（确保 WebView2 不走 HTTP 代理访问本地地址）
3. 初始化插件：opener, dialog, clipboard-manager, process, updater
4. macOS: 检测并删除旧版 `Claude Code Launcher.app`（迁移清理）
5. 注册所有 Tauri 命令
6. 应用退出时调用 `BridgeManager::stop_all()` 停止所有 bridge 服务

---

## 11. 常见问题

### 11.1 端口 1420 被占用

```
Error: Port 1420 is already in use
```

Vite 配置了 `strictPort: true`，端口被占用时直接报错。解决方法：

```bash
# Windows - 查找占用端口的进程
netstat -ano | findstr :1420
# 结束进程
taskkill /PID <PID> /F

# macOS
lsof -i :1420
kill <PID>
```

### 11.2 Cargo 编译失败

**链接器错误** (`linking with 'link.exe' failed`):
- 确认已安装 Visual Studio C++ Build Tools
- 重启终端使环境变量生效

**依赖下载超时**:
```bash
# 使用国内镜像（在 ~/.cargo/config.toml 中配置）
[source.crates-io]
replace-with = 'ustc'

[source.ustc]
registry = "sparse+https://mirrors.ustc.edu.cn/crates.io-index/"
```

### 11.3 版本不一致错误

CI 报错 `Version mismatch! All three files must have the same version.`

检查并同步以下三个文件的版本号：
- `package.json` -- `"version"`
- `src-tauri/Cargo.toml` -- `version`
- `src-tauri/tauri.conf.json` -- `"version"`

### 11.4 npm 依赖安装失败

```bash
# 使用国内镜像
npm config set registry https://registry.npmmirror.com

# 清理缓存后重试
npm cache clean --force
npm install
```

### 11.5 bridge_admin.json 缺失

本地开发时 `src-tauri/resources/bridge/bridge_admin.json` 被 `.gitignore` 排除。需要手动创建该文件（向团队获取内容），否则 Bridge Admin API 相关功能无法工作。CI 中通过 `secrets.BRIDGE_ADMIN_JSON` 自动注入。

### 11.6 .exe 资源文件被 .gitignore 排除

`.gitignore` 全局排除 `*.exe`。若需要在 `src-tauri/resources/` 下添加新的 `.exe` 文件：
- 方法一：在 `.gitignore` 中添加 `!path/to/your.exe` 例外规则（参考 MinGit 的做法）
- 方法二：将 `.exe` 重命名为 `.bin` 存储，运行时再重命名回来（参考 python-embed 的做法）

验证文件是否被忽略：
```bash
git check-ignore -v path/to/file.exe
```
