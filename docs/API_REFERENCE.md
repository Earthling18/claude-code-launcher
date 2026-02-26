# API 参考文档

> **Tauri Commands API 完整参考**
> **最后更新**: 2026-02-26
> **API 数量**: 37 个 Tauri Commands

---

## 📋 目录

- [1. API 概览](#1-api-概览)
- [2. 依赖检测 API](#2-依赖检测-api)
- [3. 安装/更新 API](#3-安装更新-api)
- [4. 启动器 API](#4-启动器-api)
- [5. 设置管理 API](#5-设置管理-api)
- [6. 应用配置 API](#6-应用配置-api)
- [7. 项目管理 API](#7-项目管理-api)
- [8. 桥接管理 API](#8-桥接管理-api)
- [9. 数据类型](#9-数据类型)
- [10. 错误处理](#10-错误处理)
- [11. 使用示例](#11-使用示例)
- [12. 总结](#12-总结)

---

## 1. API 概览

### 1.1 所有可用 Commands (37 个)

| 分类 | Command 名称 | 说明 |
|------|--------------|------|
| **依赖检测** | `check_nodejs` | 检测 Node.js 安装状态 |
| | `check_claude` | 检测 Claude Code 安装状态 |
| | `check_gitbash` | 检测 Git Bash 安装状态 |
| | `check_nodejs_with_update` | 检测 Node.js 并获取最新版本 |
| | `check_claude_with_update` | 检测 Claude Code 并获取最新版本 |
| | `check_gitbash_with_update` | 检测 Git Bash 并获取最新版本 |
| | `refresh_system_path` | 刷新系统 PATH 环境变量 |
| **安装/更新** | `install_nodejs` | 安装 Node.js |
| | `update_nodejs` | 更新 Node.js |
| | `install_claude` | 安装 Claude Code |
| | `update_claude` | 更新 Claude Code |
| | `install_gitbash` | 安装 Git Bash |
| | `update_gitbash` | 更新 Git Bash |
| **启动器** | `launch_claude_code` | 启动 Claude Code |
| | `generate_powershell_command` | 生成 PowerShell 命令 |
| | `generate_cmd_command` | 生成 CMD 命令 |
| | `generate_bash_command` | 生成 Bash 命令 |
| **平台检测** | `get_platform` | 获取当前操作系统平台 |
| | `get_home_directory` | 获取用户主目录 |
| **设置管理** | `save_to_settings` | 保存配置到 Claude 设置 |
| | `reset_settings` | 重置 Claude 设置 |
| | `open_settings_file` | 打开设置文件 |
| **应用配置** | `save_app_config` | 保存应用配置 |
| | `load_app_config` | 加载应用配置 |
| **项目管理** | `get_projects` | 获取所有项目列表 |
| | `get_project` | 获取单个项目详情 |
| | `create_project` | 创建新项目 |
| | `update_project` | 更新项目配置 |
| | `delete_project` | 删除项目 |
| | `launch_project` | 启动指定项目 |
| | `select_directory` | 选择目录对话框 |
| | `generate_project_powershell_command` | 生成项目的 PowerShell 命令 |
| | `generate_project_cmd_command` | 生成项目的 CMD 命令 |
| | `generate_project_bash_command` | 生成项目的 Bash 命令 |
| **桥接管理** | `get_hostname` | 获取本机主机名（Bridge client_id） |
| | `get_username` | 获取当前系统用户名（小写） |
| | `bridge_get_or_create_key` | 通过 Admin API 创建/获取用户 API Key |

### 1.2 调用方式

```typescript
import { invoke } from "@tauri-apps/api/core";

// 无参数调用
const status = await invoke<DependencyStatus>('check_nodejs');

// 带参数调用
await invoke('launch_claude_code', { config: { /* ... */ } });
```

---

## 2. 依赖检测 API

### 2.1 check_nodejs

**说明**: 检测 Node.js 安装状态和版本

**前端调用**:
```typescript
invoke<DependencyStatus>('check_nodejs')
```

**参数**: 无

**返回值**: `DependencyStatus`

**返回示例**:
```json
{
  "installed": true,
  "version": "20.10.0",
  "meets_requirement": true,
  "latest_version": null,
  "update_available": false,
  "error": null
}
```

**检测逻辑**:
1. 执行 `node --version` 命令
2. 使用正则 `v(\d+\.\d+\.\d+)` 提取版本号
3. 检查是否满足最低要求 (≥18.0.0)
4. 失败时尝试刷新 PATH 后重试

**错误情况**:
```json
{
  "installed": false,
  "version": null,
  "meets_requirement": false,
  "latest_version": null,
  "update_available": false,
  "error": "未安装或不在 PATH 中"
}
```

---

### 2.2 check_claude

**说明**: 检测 Claude Code 安装状态和版本

**前端调用**:
```typescript
invoke<DependencyStatus>('check_claude')
```

**参数**: 无

**返回值**: `DependencyStatus`

**返回示例**:
```json
{
  "installed": true,
  "version": "2.0.37",
  "meets_requirement": true,
  "latest_version": null,
  "update_available": false,
  "error": null
}
```

**检测方法**:
1. **方法 1**: `npm list -g @anthropic-ai/claude-code --depth=0`
   - 正则: `@anthropic-ai/claude-code@(\d+\.\d+\.\d+)`
2. **方法 2**: `claude --version`
   - 正则: `(\d+\.\d+\.\d+)`
3. 任一方法成功即返回结果

**错误情况**:
```json
{
  "installed": false,
  "version": null,
  "meets_requirement": false,
  "latest_version": null,
  "update_available": false,
  "error": "未安装或不在 PATH 中"
}
```

---

### 2.3 check_nodejs_with_update

**说明**: 检测 Node.js 并获取最新可用版本

**前端调用**:
```typescript
invoke<DependencyStatus>('check_nodejs_with_update')
```

**参数**: 无

**返回值**: `DependencyStatus`

**返回示例**:
```json
{
  "installed": true,
  "version": "20.10.0",
  "meets_requirement": true,
  "latest_version": "22.0.0",
  "update_available": true,
  "error": null
}
```

**获取最新版本**:
- 执行 `winget show OpenJS.NodeJS.LTS`
- 正则提取: `Version:\s*(\d+\.\d+\.\d+)`
- 比较当前版本和最新版本

**注意事项**:
- 需要 winget 可用
- 首先调用 `check_nodejs()` 检测当前状态
- 如果已安装，再获取最新版本信息

---

### 2.4 check_claude_with_update

**说明**: 检测 Claude Code 并获取最新可用版本（异步）

**前端调用**:
```typescript
invoke<DependencyStatus>('check_claude_with_update')
```

**参数**: 无

**返回值**: `Promise<DependencyStatus>`

**返回示例**:
```json
{
  "installed": true,
  "version": "2.0.37",
  "meets_requirement": true,
  "latest_version": "2.1.0",
  "update_available": true,
  "error": null
}
```

**获取最新版本**:
- HTTP 请求: `https://registry.npmjs.org/@anthropic-ai/claude-code/latest`
- 解析 JSON 响应中的 `version` 字段
- 比较当前版本和最新版本

**注意事项**:
- 异步操作，需要网络连接
- 首先调用 `check_claude()` 检测当前状态
- 网络失败时 `latest_version` 为 `null`

---

### 2.5 check_gitbash

**说明**: 检测 Git Bash 安装状态和版本 (Windows)

**前端调用**:
```typescript
invoke<DependencyStatus>('check_gitbash')
```

**参数**: 无

**返回值**: `DependencyStatus`

**返回示例**:
```json
{
  "installed": true,
  "version": "2.43.0",
  "meets_requirement": true,
  "latest_version": null,
  "update_available": false,
  "error": null
}
```

**检测方法**:
1. 执行 `git --version` 命令
2. 检查 `C:\Program Files\Git\bin\bash.exe` 是否存在
3. 正则提取版本号

---

### 2.6 check_gitbash_with_update

**说明**: 检测 Git Bash 并获取最新可用版本

**前端调用**:
```typescript
invoke<DependencyStatus>('check_gitbash_with_update')
```

**参数**: 无

**返回值**: `DependencyStatus`

**返回示例**:
```json
{
  "installed": true,
  "version": "2.43.0",
  "meets_requirement": true,
  "latest_version": "2.44.0",
  "update_available": true,
  "error": null
}
```

**获取最新版本**:
- 执行 `winget show Git.Git` 获取最新版本
- 比较当前版本和最新版本

---

### 2.7 refresh_system_path

**说明**: 刷新当前进程的 PATH 环境变量（Windows）

**前端调用**:
```typescript
invoke('refresh_system_path')
```

**参数**: 无

**返回值**: `Promise<void>`

**操作流程**:
1. 读取注册表系统 PATH: `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment\Path`
2. 读取注册表用户 PATH: `HKCU\Environment\Path`
3. 合并两个 PATH
4. 去重路径
5. 设置到当前进程环境变量

**使用场景**:
- 刚安装 Node.js 或 Claude Code 后
- 手动修改环境变量后
- 检测失败但确信已安装时

**错误处理**:
```typescript
try {
  await invoke('refresh_system_path');
  // 刷新成功，可以重新检测依赖
} catch (error) {
  console.error('刷新 PATH 失败:', error);
}
```

---

## 3. 安装/更新 API

### 3.1 install_nodejs

**说明**: 安装 Node.js LTS 版本（Windows）

**前端调用**:
```typescript
invoke('install_nodejs')
```

**参数**: 无

**返回值**: `Promise<void>`

**安装流程**:
1. 检查 winget 是否可用
2. 如果可用，在新控制台窗口执行 `winget install OpenJS.NodeJS.LTS`
3. 如果不可用，打开 Node.js 官网下载页面

**PowerShell 脚本**:
```powershell
Write-Host "正在安装 Node.js LTS..." -ForegroundColor Green
winget install OpenJS.NodeJS.LTS

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Node.js 安装成功！" -ForegroundColor Green
    Write-Host "请关闭此窗口并重新启动应用。" -ForegroundColor Yellow
} else {
    Write-Host "`n✗ Node.js 安装失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
    Write-Host "请检查网络连接或手动安装。" -ForegroundColor Yellow
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
```

**注意事项**:
- 在独立控制台窗口执行，不阻塞主界面
- 安装后需要重新启动应用或刷新 PATH
- 需要管理员权限（winget 自动提示）

**错误处理**:
```typescript
try {
  await invoke('install_nodejs');
  // 安装命令已执行，用户在新窗口操作
} catch (error) {
  // winget 不可用或启动失败
  alert(`安装失败: ${error}`);
}
```

---

### 3.2 update_nodejs

**说明**: 更新 Node.js 到最新 LTS 版本

**前端调用**:
```typescript
invoke('update_nodejs')
```

**参数**: 无

**返回值**: `Promise<void>`

**更新流程**:
1. 检查 winget 是否可用
2. 在新控制台窗口执行 `winget upgrade OpenJS.NodeJS.LTS`

**PowerShell 脚本**:
```powershell
Write-Host "正在更新 Node.js..." -ForegroundColor Green
winget upgrade OpenJS.NodeJS.LTS

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Node.js 更新成功！" -ForegroundColor Green
} else {
    Write-Host "`n✗ Node.js 更新失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
```

**使用示例**:
```typescript
if (status.update_available) {
  await invoke('update_nodejs');
  await invoke('refresh_system_path');
  const newStatus = await invoke<DependencyStatus>('check_nodejs');
}
```

---

### 3.3 install_claude

**说明**: 安装 Claude Code CLI 工具

**前端调用**:
```typescript
invoke('install_claude')
```

**参数**: 无

**返回值**: `Promise<void>`

**安装流程**:
- 在新控制台窗口执行 `npm install -g @anthropic-ai/claude-code`

**PowerShell 脚本**:
```powershell
Write-Host "正在安装 Claude Code..." -ForegroundColor Green
npm install -g @anthropic-ai/claude-code

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Claude Code 安装成功！" -ForegroundColor Green
} else {
    Write-Host "`n✗ Claude Code 安装失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
    Write-Host "请检查 Node.js 是否正确安装。" -ForegroundColor Yellow
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
```

**前置条件**:
- 必须先安装 Node.js
- npm 必须在 PATH 中

---

### 3.4 update_claude

**说明**: 更新 Claude Code 到最新版本

**前端调用**:
```typescript
invoke('update_claude')
```

**参数**: 无

**返回值**: `Promise<void>`

**更新流程**:
- 在新控制台窗口执行 `npm install -g @anthropic-ai/claude-code@latest`

**PowerShell 脚本**:
```powershell
Write-Host "正在更新 Claude Code..." -ForegroundColor Green
npm install -g @anthropic-ai/claude-code@latest

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Claude Code 更新成功！" -ForegroundColor Green
} else {
    Write-Host "`n✗ Claude Code 更新失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
}

Write-Host "`n按任意键关闭窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
```

---

### 3.5 install_gitbash

**说明**: 安装 Git Bash

**前端调用**:
```typescript
invoke('install_gitbash')
```

**参数**: 无

**返回值**: `Promise<void>`

**安装流程**:
- Windows: 在新控制台窗口执行 `winget install Git.Git`
- macOS: 在终端执行 `brew install git`

**注意事项**:
- Windows 需要 winget 可用
- macOS 需要 Homebrew 可用
- 安装后需要重新启动应用或刷新 PATH

---

### 3.6 update_gitbash

**说明**: 更新 Git Bash 到最新版本

**前端调用**:
```typescript
invoke('update_gitbash')
```

**参数**: 无

**返回值**: `Promise<void>`

**更新流程**:
- Windows: `winget upgrade Git.Git`
- macOS: `brew upgrade git`

---

## 4. 启动器 API

### 4.1 launch_claude_code

**说明**: 使用指定环境变量配置启动 Claude Code

**前端调用**:
```typescript
invoke('launch_claude_code', {
  config: {
    'ANTHROPIC_MODEL': 'qwen3-coder-480b-a35b',
    'ANTHROPIC_BASE_URL': 'http://api.example.com',
    'ANTHROPIC_AUTH_TOKEN': 'token',
  }
})
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `config` | `Record<string, string>` | 是 | 环境变量配置字典 |

**返回值**: `Promise<void>`

**环境变量支持**:
- `HTTP_PROXY`: HTTP 代理地址
- `HTTPS_PROXY`: HTTPS 代理地址
- `ANTHROPIC_MODEL`: 自定义模型名称
- `ANTHROPIC_BASE_URL`: 自定义 API 地址
- `ANTHROPIC_AUTH_TOKEN`: 认证令牌

**启动流程**:
1. 检查 `claude` 命令是否存在
2. 获取用户主目录
3. 构建 PowerShell 脚本
4. 在新控制台窗口启动

**生成的 PowerShell 命令**:
```powershell
& { $env:ANTHROPIC_MODEL="qwen3-coder-480b-a35b"; $env:ANTHROPIC_BASE_URL="http://api.example.com"; $env:ANTHROPIC_AUTH_TOKEN="token"; claude }
```

**窗口特性**:
- 使用 `-NoExit` 保持窗口打开
- `CREATE_NEW_CONSOLE` 创建新窗口
- 在用户主目录启动

**错误处理**:
```typescript
try {
  await invoke('launch_claude_code', { config });
  alert('Claude Code 已启动！');
} catch (error) {
  alert(`启动失败: ${error}`);
  // 可能的错误：
  // - "Claude Code 未安装或不在 PATH 中"
  // - "无法获取用户主目录"
  // - "启动失败: <系统错误>"
}
```

---

### 4.2 generate_powershell_command

**说明**: 生成 PowerShell 格式的启动命令

**前端调用**:
```typescript
const command = await invoke<string>('generate_powershell_command', {
  config: {
    'ANTHROPIC_MODEL': 'qwen3-coder-480b-a35b',
    'HTTP_PROXY': 'http://127.0.0.1:7890',
  }
});
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `config` | `Record<string, string>` | 是 | 环境变量配置字典 |

**返回值**: `Promise<string>`

**返回示例**:
```powershell
$env:ANTHROPIC_MODEL="qwen3-coder-480b-a35b";$env:HTTP_PROXY="http://127.0.0.1:7890";claude
```

**特殊字符转义**:
- `"` 转义为 `` `" ``

**使用场景**:
- 复制命令到剪贴板
- 手动在 PowerShell 中执行
- 集成到自动化脚本

---

### 4.3 generate_cmd_command

**说明**: 生成 CMD 格式的启动命令

**前端调用**:
```typescript
const command = await invoke<string>('generate_cmd_command', {
  config: {
    'ANTHROPIC_MODEL': 'qwen3-coder-480b-a35b',
    'HTTP_PROXY': 'http://127.0.0.1:7890',
  }
});
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `config` | `Record<string, string>` | 是 | 环境变量配置字典 |

**返回值**: `Promise<string>`

**返回示例**:
```cmd
set ANTHROPIC_MODEL=qwen3-coder-480b-a35b & set HTTP_PROXY=http://127.0.0.1:7890 & claude
```

**格式说明**:
- 使用 `set VAR=value` 设置环境变量
- 使用 `&` 连接多个命令
- 最后执行 `claude`

**使用场景**:
- 在 CMD 窗口中执行
- Windows 批处理脚本
- 兼容旧版 Windows

---

### 4.4 generate_bash_command

**说明**: 生成 Bash 格式的启动命令 (macOS/Linux/Git Bash)

**前端调用**:
```typescript
const command = await invoke<string>('generate_bash_command', {
  config: {
    'ANTHROPIC_MODEL': 'qwen3-coder-480b-a35b',
    'HTTP_PROXY': 'http://127.0.0.1:7890',
  }
});
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `config` | `Record<string, string>` | 是 | 环境变量配置字典 |

**返回值**: `Promise<string>`

**返回示例**:
```bash
ANTHROPIC_MODEL="qwen3-coder-480b-a35b" HTTP_PROXY="http://127.0.0.1:7890" claude --dangerously-skip-permissions
```

**格式说明**:
- 使用 `VAR="value"` 设置环境变量
- 环境变量放在命令前面（内联设置）
- 最后执行 `claude` 命令

**使用场景**:
- 在 macOS Terminal 中执行
- 在 Linux 终端中执行
- 在 Windows Git Bash 中执行
- Shell 脚本

---

### 4.5 get_platform

**说明**: 获取当前操作系统平台

**前端调用**:
```typescript
const platform = await invoke<string>('get_platform');
```

**参数**: 无

**返回值**: `Promise<string>`

**返回值说明**:

| 返回值 | 说明 |
|--------|------|
| `"windows"` | Windows 系统 |
| `"macos"` | macOS 系统 |
| `"linux"` | Linux 系统 |
| `"unknown"` | 未知系统 |

**使用示例**:
```typescript
const platform = await api.getPlatform();

if (platform === 'windows') {
  // 显示 PowerShell 和 CMD 选项
} else {
  // 显示 Bash 选项
}
```

**使用场景**:
- 根据平台显示不同的 UI 选项
- 选择合适的命令格式
- 条件性功能启用

---

## 5. 设置管理 API

### 5.1 save_to_settings

**说明**: 将配置保存到 `~/.claude/settings.json`

**前端调用**:
```typescript
await invoke('save_to_settings', {
  config: {
    'ANTHROPIC_MODEL': 'qwen3-coder-480b-a35b',
    'ANTHROPIC_BASE_URL': 'http://api.example.com',
  }
});
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `config` | `Record<string, string>` | 是 | 环境变量配置字典 |

**返回值**: `Promise<void>`

**配置文件路径**: `~/.claude/settings.json`

**操作流程**:
1. 检查 `.claude` 目录是否存在
2. 读取现有 `settings.json`（如果存在）
3. 合并配置到 `env` 字段
4. 格式化写入 JSON

**配置示例**:

**原始文件**:
```json
{
  "theme": "dark"
}
```

**调用**:
```typescript
await invoke('save_to_settings', {
  config: {
    'ANTHROPIC_MODEL': 'qwen3-coder-480b-a35b',
  }
});
```

**结果文件**:
```json
{
  "theme": "dark",
  "env": {
    "ANTHROPIC_MODEL": "qwen3-coder-480b-a35b"
  }
}
```

**错误处理**:
```typescript
try {
  await invoke('save_to_settings', { config });
  alert('配置已保存到 Claude 设置！');
} catch (error) {
  // 可能的错误：
  // - "Claude Code 未初始化，请先运行 'claude' 命令"
  // - "读取配置文件失败: <系统错误>"
  // - "写入配置文件失败: <系统错误>"
  alert(`保存失败: ${error}`);
}
```

**注意事项**:
- 不会覆盖其他配置字段
- 仅更新 `env` 中的指定变量
- 配置永久生效，直接运行 `claude` 即可使用

---

### 5.2 reset_settings

**说明**: 重置 Claude 设置中的环境变量配置

**前端调用**:
```typescript
await invoke('reset_settings')
```

**参数**: 无

**返回值**: `Promise<void>`

**操作流程**:
1. 读取 `~/.claude/settings.json`
2. 删除 `env` 字段中的以下变量：
   - `ANTHROPIC_MODEL`
   - `ANTHROPIC_BASE_URL`
   - `ANTHROPIC_AUTH_TOKEN`
   - `HTTP_PROXY`
   - `HTTPS_PROXY`
3. 如果 `env` 为空，删除整个 `env` 字段
4. 如果配置文件为空，删除文件

**示例**:

**原始文件**:
```json
{
  "theme": "dark",
  "env": {
    "ANTHROPIC_MODEL": "qwen3-coder-480b-a35b",
    "ANTHROPIC_BASE_URL": "http://api.example.com",
    "CUSTOM_VAR": "value"
  }
}
```

**调用重置**:
```typescript
await invoke('reset_settings');
```

**结果文件**:
```json
{
  "theme": "dark",
  "env": {
    "CUSTOM_VAR": "value"
  }
}
```

**使用场景**:
- 恢复默认配置
- 清除自定义模型设置
- 移除代理配置

**错误处理**:
```typescript
if (confirm('确定要重置 Claude 设置中的环境变量配置吗？')) {
  try {
    await invoke('reset_settings');
    alert('设置已重置！');
  } catch (error) {
    alert(`重置失败: ${error}`);
  }
}
```

---

### 5.3 open_settings_file

**说明**: 使用默认编辑器打开 `~/.claude/settings.json`

**前端调用**:
```typescript
await invoke('open_settings_file')
```

**参数**: 无

**返回值**: `Promise<void>`

**操作流程**:
1. 检查 `~/.claude/settings.json` 是否存在
2. 使用默认编辑器打开文件

**Windows 实现**:
```bash
cmd /C start "" "C:\Users\username\.claude\settings.json"
```

**macOS/Linux 实现**:
```bash
open ~/.claude/settings.json
```

**使用场景**:
- 查看完整配置
- 手动修改高级选项
- 调试配置问题

**错误处理**:
```typescript
try {
  await invoke('open_settings_file');
} catch (error) {
  // 可能的错误：
  // - "设置文件不存在"
  // - "打开文件失败: <系统错误>"
  alert(`打开设置文件失败: ${error}`);
}
```

---

## 6. 应用配置 API

### 6.1 save_app_config

**说明**: 保存应用配置到 `%APPDATA%\ClaudeCodeLauncher\config.json`

**前端调用**:
```typescript
await invoke('save_app_config', {
  config: {
    mode: 'custom',
    proxy: '',
    model: 'qwen3-coder-480b-a35b',
    base_url: 'http://api.example.com',
    token: 'my-token',
  }
});
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `config` | `AppConfig` | 是 | 应用配置对象 |

**AppConfig 结构**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | `'claude' \| 'custom'` | 工作模式 |
| `proxy` | `string` | 代理地址 |
| `model` | `string` | 模型名称 |
| `base_url` | `string` | API Base URL |
| `token` | `string` | 认证令牌 |

**返回值**: `Promise<void>`

**配置文件路径**: `%APPDATA%\ClaudeCodeLauncher\config.json`

**安全特性**:
- Token 使用 Base64 编码存储（简单混淆，非加密）

**存储示例**:
```json
{
  "mode": "custom",
  "proxy": "",
  "model": "qwen3-coder-480b-a35b",
  "base_url": "http://api.example.com",
  "token": "bXktdG9rZW4="
}
```

**使用场景**:
- 窗口关闭时自动保存配置
- 用户点击保存按钮
- 配置变更时持久化

**错误处理**:
```typescript
try {
  await invoke('save_app_config', { config });
} catch (error) {
  console.error('保存配置失败:', error);
}
```

---

### 6.2 load_app_config

**说明**: 加载应用配置

**前端调用**:
```typescript
const config = await invoke<AppConfig>('load_app_config');
```

**参数**: 无

**返回值**: `Promise<AppConfig>`

**返回示例**:
```json
{
  "mode": "custom",
  "proxy": "",
  "model": "qwen3-coder-480b-a35b",
  "base_url": "http://api.example.com",
  "token": "my-token"
}
```

**操作流程**:
1. 检查配置文件是否存在
2. 如果不存在，返回默认配置
3. 如果存在，读取并解析 JSON
4. 解码 Base64 编码的 Token
5. 返回配置对象

**默认配置**:
```typescript
{
  mode: 'claude',
  proxy: '',
  model: 'qwen3-coder-480b-a35b',
  base_url: 'http://litellm.uattest.weoa.com',
  token: '',
}
```

**使用场景**:
- 应用启动时加载配置
- 恢复用户上次的设置

**错误处理**:
```typescript
try {
  const config = await invoke<AppConfig>('load_app_config');
  // 应用配置到状态
} catch (error) {
  console.error('加载配置失败:', error);
  // 使用默认配置
}
```

---

## 7. 项目管理 API

### 7.1 get_projects

**说明**: 获取所有项目列表

**前端调用**:
```typescript
const projects = await invoke<Project[]>('get_projects');
```

**参数**: 无

**返回值**: `Promise<Project[]>`

**返回示例**:
```json
[
  {
    "id": "abc123-def456",
    "name": "默认项目",
    "working_directory": "C:\\Users\\username",
    "config": {
      "mode": "claude",
      "proxy": "",
      "model": "",
      "base_url": "",
      "token": "",
      "skip_permissions": true
    },
    "is_default": true,
    "created_at": 1706918400,
    "updated_at": 1706918400,
    "last_launched_at": null
  }
]
```

---

### 7.2 get_project

**说明**: 获取单个项目详情

**前端调用**:
```typescript
const project = await invoke<Project>('get_project', { id: 'project-id' });
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `id` | `string` | 是 | 项目 ID |

**返回值**: `Promise<Project>`

**错误情况**:
- `"项目不存在: <id>"`: 指定 ID 的项目不存在

---

### 7.3 create_project

**说明**: 创建新项目

**前端调用**:
```typescript
const project = await invoke<Project>('create_project', {
  name: '我的项目',
  working_directory: 'D:\\projects\\my-app',
  config: {
    mode: 'custom',
    proxy: '',
    model: 'qwen3-coder-480b-a35b',
    base_url: 'http://api.example.com',
    token: 'my-token',
    skip_permissions: true
  }
});
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `name` | `string` | 是 | 项目名称 |
| `working_directory` | `string` | 是 | 工作目录路径 |
| `config` | `ProjectConfig` | 是 | 项目配置 |

**返回值**: `Promise<Project>`

**注意事项**:
- 新创建的项目 `is_default` 为 `false`
- 自动生成 UUID 作为项目 ID
- 自动记录创建和更新时间戳

---

### 7.4 update_project

**说明**: 更新项目配置

**前端调用**:
```typescript
const project = await invoke<Project>('update_project', {
  id: 'project-id',
  name: '新名称',  // 可选
  working_directory: 'D:\\new\\path',  // 可选
  config: { /* ... */ }  // 可选
});
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `id` | `string` | 是 | 项目 ID |
| `name` | `string` | 否 | 新项目名称 |
| `working_directory` | `string` | 否 | 新工作目录 |
| `config` | `ProjectConfig` | 否 | 新配置 |

**返回值**: `Promise<Project>`

**注意事项**:
- 只更新提供的字段
- 自动更新 `updated_at` 时间戳

---

### 7.5 delete_project

**说明**: 删除项目

**前端调用**:
```typescript
await invoke('delete_project', { id: 'project-id' });
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `id` | `string` | 是 | 项目 ID |

**返回值**: `Promise<void>`

**错误情况**:
- `"项目不存在: <id>"`: 指定 ID 的项目不存在
- `"不能删除默认项目"`: 尝试删除默认项目

---

### 7.6 launch_project

**说明**: 启动指定项目

**前端调用**:
```typescript
await invoke('launch_project', { id: 'project-id' });
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `id` | `string` | 是 | 项目 ID |

**返回值**: `Promise<void>`

**启动流程**:
1. 获取项目配置
2. 根据模式构建环境变量
3. 使用项目的工作目录启动 Claude Code
4. 更新 `last_launched_at` 时间戳

---

### 7.7 select_directory

**说明**: 打开目录选择对话框

**前端调用**:
```typescript
const path = await invoke<string | null>('select_directory');
```

**参数**: 无

**返回值**: `Promise<string | null>`

**返回说明**:
- 用户选择目录后返回路径字符串
- 用户取消选择返回 `null`

**注意事项**:
- 使用 `tauri-plugin-dialog` 实现
- 对话框标题为 "选择项目目录"

---

### 7.8 generate_project_powershell_command

**说明**: 生成指定项目的 PowerShell 启动命令

**前端调用**:
```typescript
const command = await invoke<string>('generate_project_powershell_command', { id: 'project-id' });
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `id` | `string` | 是 | 项目 ID |

**返回值**: `Promise<string>`

**返回示例**:
```powershell
Set-Location -LiteralPath 'D:\projects\my-app';$env:ANTHROPIC_MODEL='qwen3';claude --dangerously-skip-permissions
```

---

### 7.9 generate_project_cmd_command

**说明**: 生成指定项目的 CMD 启动命令

**前端调用**:
```typescript
const command = await invoke<string>('generate_project_cmd_command', { id: 'project-id' });
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `id` | `string` | 是 | 项目 ID |

**返回值**: `Promise<string>`

---

### 7.10 generate_project_bash_command

**说明**: 生成指定项目的 Bash 启动命令

**前端调用**:
```typescript
const command = await invoke<string>('generate_project_bash_command', { id: 'project-id' });
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `id` | `string` | 是 | 项目 ID |

**返回值**: `Promise<string>`

---

### 7.11 get_home_directory

**说明**: 获取用户主目录路径

**前端调用**:
```typescript
const homeDir = await invoke<string>('get_home_directory');
```

**参数**: 无

**返回值**: `Promise<string>`

**返回示例**:
- Windows: `"C:\\Users\\username"`
- macOS: `"/Users/username"`

**错误情况**:
- `"无法获取用户主目录"`: 系统无法确定主目录

---

## 8. 桥接管理 API

### 8.1 get_hostname

**说明**: 获取本机主机名，用作 Bridge client_id。优先读取 `~/.agent-bridge/client_id` 文件，如不存在则回退到系统环境变量。

**前端调用**:
```typescript
const hostname = await invoke<string>('get_hostname');
```

**参数**: 无

**返回值**: `Promise<string>`

**返回示例**: `"shawnlin-NB1"`

**检测逻辑**:
1. 尝试读取 `~/.agent-bridge/client_id` 文件内容
2. 如果文件不存在或为空，回退到 `COMPUTERNAME` 环境变量 (Windows)
3. 再回退到 `HOSTNAME` 环境变量 (macOS/Linux)
4. 最终回退到 `"unknown"`

**使用场景**:
- 生成 `/变身 bridge:<hostname>:<key>` 连接口令

---

### 8.2 get_username

**说明**: 获取当前系统用户名（自动转为小写），用于在 Bridge Admin API 中创建/查询用户。

**前端调用**:
```typescript
const username = await invoke<string>('get_username');
```

**参数**: 无

**返回值**: `Promise<string>`

**返回示例**: `"shawnlin"`

**检测逻辑**:
1. 读取 `USERNAME` 环境变量 (Windows)
2. 回退到 `USER` 环境变量 (macOS/Linux)
3. 最终回退到 `"unknown"`
4. 结果统一转为小写

---

### 8.3 bridge_get_or_create_key

**说明**: 通过 Bridge Admin API 自动创建用户或获取已有用户的 API Key。使用 `.no_proxy()` 绕过系统代理。

**前端调用**:
```typescript
const key = await invoke<string>('bridge_get_or_create_key', { username: 'shawnlin' });
```

**参数**:

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `username` | `string` | 是 | 用户名（小写英文） |

**返回值**: `Promise<string>` — 用户的 API Key

**操作流程**:
1. 使用 `reqwest::Client::builder().no_proxy()` 构建 HTTP 客户端（绕过系统代理）
2. POST `/api/login` 登录获取 `admin_token` Cookie
3. GET `/api/admin/users/{username}` 尝试查询已有用户
4. 如果用户存在，直接返回 `api_key`
5. 如果用户不存在（404），POST `/api/admin/users` 创建新用户并返回 `api_key`

**错误情况**:
- 无法连接 Admin API（外网环境）
- 登录失败
- 创建用户失败

**错误提示**: 前端统一显示"获取失败，请联系管理员"

---

## 9. 数据类型

### 8.1 DependencyStatus

**说明**: 依赖检测状态

```typescript
interface DependencyStatus {
  installed: boolean;           // 是否已安装
  version: string | null;        // 当前版本号
  meets_requirement: boolean;    // 是否满足最低版本要求
  latest_version: string | null; // 最新可用版本
  update_available: boolean;     // 是否有可用更新
  error: string | null;          // 错误信息
}
```

**状态组合**:

| 场景 | installed | version | meets_requirement | update_available |
|------|-----------|---------|-------------------|------------------|
| 未安装 | false | null | false | false |
| 已安装，最新版 | true | "20.10.0" | true | false |
| 已安装，有更新 | true | "20.10.0" | true | true |
| 已安装，版本过低 | true | "16.0.0" | false | true |
| 检测失败 | false | null | false | false |

---

### 8.2 AppConfig

**说明**: 应用配置对象

```typescript
interface AppConfig {
  mode: 'claude' | 'custom';  // 工作模式
  proxy: string;              // 代理地址
  model: string;              // 模型名称
  base_url: string;           // API Base URL
  token: string;              // 认证令牌
  skip_permissions: boolean;  // 是否跳过权限确认
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | `'claude' \| 'custom'` | 工作模式 |
| `proxy` | `string` | 代理地址 (Claude 模式) |
| `model` | `string` | 模型名称 (自定义模式) |
| `base_url` | `string` | API Base URL (自定义模式) |
| `token` | `string` | 认证令牌 (自定义模式) |
| `skip_permissions` | `boolean` | 是否启用 `--dangerously-skip-permissions` |

**模式说明**:

**claude 模式**:
- 使用 `proxy` 字段配置代理
- `model`, `base_url`, `token` 不生效

**custom 模式**:
- 使用 `model`, `base_url`, `token` 配置自定义模型
- `proxy` 不生效

**skip_permissions 说明**:
- `true`: 启动时添加 `--dangerously-skip-permissions` 参数
- `false`: 普通模式，需要权限确认
- 默认值: `true`

**默认值**:
```typescript
{
  mode: 'claude',
  proxy: '',
  model: 'qwen3-coder-480b-a35b',
  base_url: 'http://litellm.uattest.weoa.com',
  token: '',
  skip_permissions: true,
}
```

---

### 8.3 Project

**说明**: 项目数据结构

```typescript
interface Project {
  id: string;                      // 项目 UUID
  name: string;                    // 项目名称
  working_directory: string;       // 工作目录路径
  config: ProjectConfig;           // 项目配置
  is_default: boolean;             // 是否为默认项目
  created_at: number;              // 创建时间 (Unix 时间戳)
  updated_at: number;              // 更新时间 (Unix 时间戳)
  last_launched_at: number | null; // 最后启动时间
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `string` | 自动生成的 UUID |
| `name` | `string` | 项目显示名称 |
| `working_directory` | `string` | Claude Code 启动时的工作目录 |
| `config` | `ProjectConfig` | 项目的环境配置 |
| `is_default` | `boolean` | 是否为默认项目（不可删除） |
| `created_at` | `number` | Unix 时间戳 |
| `updated_at` | `number` | Unix 时间戳 |
| `last_launched_at` | `number \| null` | 最后一次启动的时间戳 |

---

### 8.4 ProjectConfig

**说明**: 项目配置结构

```typescript
interface ProjectConfig {
  mode: 'claude' | 'custom';  // 工作模式
  proxy: string;              // 代理地址 (Claude 模式)
  model: string;              // 模型名称 (自定义模式)
  base_url: string;           // API Base URL (自定义模式)
  token: string;              // 认证令牌 (自定义模式)
  skip_permissions: boolean;  // 是否跳过权限确认
}
```

**与 AppConfig 的关系**:
- `ProjectConfig` 结构与 `AppConfig` 相同
- `AppConfig` 用于兼容旧的 V1 配置格式
- `ProjectConfig` 用于 V2 多项目配置

**默认值**:
```typescript
{
  mode: 'claude',
  proxy: '',
  model: 'qwen3-coder-480b-a35b',
  base_url: 'http://litellm.uattest.weoa.com',
  token: '',
  skip_permissions: true,
}
```

---

## 10. 错误处理

### 10.1 错误类型

所有 API 调用都返回 `Promise`，失败时会 reject 一个字符串错误消息。

**错误格式**:
```typescript
// 成功
Promise.resolve(result)

// 失败
Promise.reject("错误消息")
```

### 10.2 常见错误

| 错误消息 | 原因 | 解决方法 |
|----------|------|----------|
| "未安装或不在 PATH 中" | 依赖未安装或环境变量未配置 | 安装依赖或刷新 PATH |
| "Claude Code 未初始化" | 未运行过 `claude` 命令 | 先运行一次 `claude` |
| "winget 不可用" | winget 未安装或不在 PATH | 手动下载安装 |
| "无法获取用户主目录" | 系统环境异常 | 检查系统配置 |
| "设置文件不存在" | 从未保存过配置 | 先保存配置 |
| "启动失败: ..." | 系统调用失败 | 查看详细错误信息 |

### 10.3 错误处理模式

**模式 1: try-catch**
```typescript
try {
  const result = await invoke('some_command');
  // 成功处理
} catch (error) {
  console.error('操作失败:', error);
  alert(`操作失败: ${error}`);
}
```

**模式 2: Promise.catch()**
```typescript
invoke('some_command')
  .then(result => {
    // 成功处理
  })
  .catch(error => {
    console.error('操作失败:', error);
  });
```

**模式 3: 默认值**
```typescript
const config = await invoke<AppConfig>('load_app_config')
  .catch(() => DEFAULT_CONFIG);
```

---

## 11. 使用示例

### 11.1 完整的依赖检测流程

```typescript
async function checkAndInstallDependencies() {
  // 1. 检测 Node.js
  let nodejsStatus = await invoke<DependencyStatus>('check_nodejs');

  if (!nodejsStatus.installed) {
    // 未安装，执行安装
    await invoke('install_nodejs');
    alert('Node.js 安装已开始，请在新窗口中完成安装');

    // 安装后刷新 PATH 并重新检测
    await invoke('refresh_system_path');
    nodejsStatus = await invoke<DependencyStatus>('check_nodejs');
  }

  // 2. 检查 Node.js 更新
  if (nodejsStatus.installed) {
    nodejsStatus = await invoke<DependencyStatus>('check_nodejs_with_update');

    if (nodejsStatus.update_available) {
      const shouldUpdate = confirm(
        `有新版本 ${nodejsStatus.latest_version} 可用，是否更新？`
      );

      if (shouldUpdate) {
        await invoke('update_nodejs');
        await invoke('refresh_system_path');
      }
    }
  }

  // 3. 检测 Claude Code
  let claudeStatus = await invoke<DependencyStatus>('check_claude');

  if (!claudeStatus.installed) {
    await invoke('install_claude');
    alert('Claude Code 安装已开始');
    await invoke('refresh_system_path');
    claudeStatus = await invoke<DependencyStatus>('check_claude');
  }

  // 4. 检查 Claude Code 更新
  if (claudeStatus.installed) {
    claudeStatus = await invoke<DependencyStatus>('check_claude_with_update');

    if (claudeStatus.update_available) {
      const shouldUpdate = confirm(
        `有新版本 ${claudeStatus.latest_version} 可用，是否更新？`
      );

      if (shouldUpdate) {
        await invoke('update_claude');
      }
    }
  }

  return {
    nodejs: nodejsStatus,
    claude: claudeStatus,
  };
}
```

---

### 11.2 启动 Claude Code 的完整流程

```typescript
async function launchClaudeCode() {
  // 1. 验证配置
  if (mode === 'claude') {
    if (proxy && !proxy.startsWith('http://') && !proxy.startsWith('https://')) {
      alert('代理地址必须以 http:// 或 https:// 开头');
      return;
    }
  } else {
    if (!model || !baseUrl) {
      alert('请填写完整的模型配置');
      return;
    }
    if (!baseUrl.startsWith('http://') && !baseUrl.startsWith('https://')) {
      alert('Base URL 必须以 http:// 或 https:// 开头');
      return;
    }
  }

  // 2. 构建配置
  const config: Record<string, string> = {};

  if (mode === 'claude') {
    if (proxy) {
      config['HTTP_PROXY'] = proxy;
      config['HTTPS_PROXY'] = proxy;
    }
  } else {
    config['ANTHROPIC_MODEL'] = model;
    config['ANTHROPIC_BASE_URL'] = baseUrl;
    if (token) {
      config['ANTHROPIC_AUTH_TOKEN'] = token;
    }
  }

  // 3. 启动
  try {
    await invoke('launch_claude_code', { config });
    alert('Claude Code 已启动！');
  } catch (error) {
    alert(`启动失败: ${error}`);
  }
}
```

---

### 11.3 配置管理的完整流程

```typescript
// 启动时加载配置
useEffect(() => {
  loadConfig();
}, []);

async function loadConfig() {
  try {
    const config = await invoke<AppConfig>('load_app_config');
    setMode(config.mode);
    setProxy(config.proxy);
    setModel(config.model);
    setBaseUrl(config.base_url);
    setToken(config.token);
  } catch (error) {
    console.error('加载配置失败:', error);
    // 使用默认值
  }
}

// 配置变更时自动保存
useEffect(() => {
  const saveConfig = async () => {
    try {
      const config: AppConfig = {
        mode,
        proxy,
        model,
        base_url: baseUrl,
        token,
      };
      await invoke('save_app_config', { config });
    } catch (error) {
      console.error('保存配置失败:', error);
    }
  };

  // 防抖保存
  const timer = setTimeout(saveConfig, 1000);
  return () => clearTimeout(timer);
}, [mode, proxy, model, baseUrl, token]);

// 保存到 Claude 设置
async function saveToClaudeSettings() {
  const config: Record<string, string> = {};

  if (mode === 'claude') {
    if (proxy) {
      config['HTTP_PROXY'] = proxy;
      config['HTTPS_PROXY'] = proxy;
    }
  } else {
    config['ANTHROPIC_MODEL'] = model;
    config['ANTHROPIC_BASE_URL'] = baseUrl;
    if (token) {
      config['ANTHROPIC_AUTH_TOKEN'] = token;
    }
  }

  try {
    await invoke('save_to_settings', { config });
    alert('配置已保存到 Claude 设置！');
  } catch (error) {
    alert(`保存失败: ${error}`);
  }
}
```

---

### 11.4 生成和复制命令

```typescript
import { writeText } from "@tauri-apps/plugin-clipboard-manager";

async function copyCommand(type: 'powershell' | 'cmd' | 'bash') {
  // 1. 构建配置
  const config: Record<string, string> = {};

  if (mode === 'claude') {
    if (proxy) {
      config['HTTP_PROXY'] = proxy;
      config['HTTPS_PROXY'] = proxy;
    }
  } else {
    config['ANTHROPIC_MODEL'] = model;
    config['ANTHROPIC_BASE_URL'] = baseUrl;
    if (token) {
      config['ANTHROPIC_AUTH_TOKEN'] = token;
    }
  }

  // 2. 生成命令
  try {
    let command: string;
    switch (type) {
      case 'powershell':
        command = await invoke<string>('generate_powershell_command', { config });
        break;
      case 'cmd':
        command = await invoke<string>('generate_cmd_command', { config });
        break;
      case 'bash':
        command = await invoke<string>('generate_bash_command', { config });
        break;
    }

    // 3. 复制到剪贴板
    await writeText(command);

    // 4. 显示成功提示
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  } catch (error) {
    alert(`生成命令失败: ${error}`);
  }
}

// 根据平台选择命令类型
async function detectPlatformAndCopy() {
  const platform = await invoke<string>('get_platform');

  if (platform === 'windows') {
    // Windows: 默认使用 PowerShell
    await copyCommand('powershell');
  } else {
    // macOS/Linux: 使用 Bash
    await copyCommand('bash');
  }
}
```

---

## 12. 总结

### 12.1 API 设计特点

- ✅ **命名清晰**: 函数名直接表达功能
- ✅ **类型安全**: 完整的 TypeScript 类型定义
- ✅ **错误友好**: 详细的中文错误提示
- ✅ **异步优先**: 所有 I/O 操作均为异步
- ✅ **职责单一**: 每个 API 只做一件事
- ✅ **跨平台**: 支持 Windows 和 macOS

### 12.2 API 统计

| 分类 | 数量 |
|------|------|
| 依赖检测 | 7 |
| 安装/更新 | 6 |
| 启动器 | 4 |
| 平台/工具 | 2 |
| 设置管理 | 3 |
| 应用配置 | 2 |
| 项目管理 | 10 |
| 桥接管理 | 3 |
| **总计** | **37** |

### 12.3 使用建议

1. **依赖检测**: 应用启动时自动检测，检测失败时刷新 PATH 后重试
2. **安装/更新**: 在新窗口执行，不阻塞主界面
3. **启动器**: 验证配置后再调用
4. **平台检测**: 启动时调用一次，用于 UI 适配
5. **设置管理**: 保存前确认用户意图
6. **配置存储**: 窗口关闭时自动保存

### 12.4 相关文档

- [项目总览](./PROJECT_DOCUMENTATION.md)
- [前端开发指南](./FRONTEND_GUIDE.md)
- [后端开发指南](./BACKEND_GUIDE.md)
