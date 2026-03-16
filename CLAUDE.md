---
indexed_by: xiaobai-file-index
indexed_date: "2026-03-13"
category: 开发项目
tags: [rust, tauri, react, typescript, claude-sdk, mobot]
---

# Mobot Launcher (claude-code-launcher-tauri)

Mobot Launcher 桌面启动器完整源码，Tauri 2应用，支持多项目管理、5种启动模式（原生/自定义/Codex/远程Bridge/Mobot）、自动更新。

## 技术栈
- Frontend: React 19 + TypeScript + Tailwind CSS + Vite 7
- Desktop: Tauri 2 (Rust)
- Backend: Rust + Python Bridge (FastAPI + Claude Agent SDK)
- UI: @dnd-kit (拖拽排序), React Router 7
- Plugins: Clipboard, Dialog, Process, Updater, Opener

## 主要内容
- src/ — React前端
  - pages/ — 页面组件（6个：模式选择、项目列表/详情/编辑/创建、远程Bridge）
  - components/ — 通用组件（16个：配置面板、安装向导、依赖检测、拖拽卡片等）
  - hooks/ — 自定义Hooks（useUpdateChecker）
  - types/ — TypeScript类型定义
  - api.ts — Tauri API调用层
  - App.tsx — 应用入口（路由 + 拖拽上下文）
- src-tauri/ — Rust后端
  - Cargo.toml — Rust依赖配置
  - tauri.conf.json — Tauri配置（v1.0.5）
  - src/commands/ — 70个Tauri命令
  - src/services/ — 8个服务模块（~5000行）
  - resources/bridge/ — Python Bridge源码 + MinGit + 嵌入式Python
  - windows/hooks.nsh — NSIS安装器钩子
  - icons/ — 应用图标
- .github/ — CI/CD配置（GitHub Actions: Windows NSIS + macOS Universal）
- docs/ — 技术文档

## 功能特性
- 项目CRUD + 拖拽排序 + 置顶
- 5种启动模式：原生/自定义/Codex/远程Bridge/Mobot
- Codex CLI支持：独立代理配置、自定义模式、依赖检测与一键安装
- 远程Bridge：Python FastAPI + Claude Agent SDK，WebSocket长连接
- 远程Bridge自动获取Key：通过管理后台API自动创建/获取用户Bind Key，基于OS用户名识别
- 远程Bridge连接提示：显示可复制的 /变身 命令 + 艾灵企微二维码
- 远程Bridge热更新：updater.py管理代码更新，restart_helper自动重启
- 启动桥接时自动保存配置
- 依赖检测 + 一键安装 + npm shim自动修复（Windows/macOS，启动/检测时若shim丢失则静默重建）
- Git安装过程检测：防止Inno Setup未完成就误判已安装
- MinGit打包：远程模式自动携带Git/bash，无需用户安装
- 嵌入式Python：Windows内置Python运行时，完全离线
- 老用户升级资源自动释放：ensure_bundled_resources检测并补充新增资源
- 关闭app时自动清理bridge进程（RunEvent::Exit + 端口清理）
- macOS：Homebrew-free Node.js安装、xcode-select优先的Git安装
- 自动更新（GitHub Releases + Tauri Updater签名验证）
- 便携模式：portable zip包支持，.portable标记文件
- CC配置检查器：扫描配置冲突、BOM问题、MCP错位，自动修复
- 新手引导（OnboardingOverlay）
- WebView2 Runtime自动安装（embedBootstrapper）
- NSIS安装器钩子：旧版"Claude Code Launcher"自动迁移清理

## Rust服务模块
- bridge_manager.rs — Bridge安装/启动/健康检查/资源释放/进程管理
- dependency_checker.rs — Node.js/Claude/Git/Codex版本检测与更新检查
- installer.rs — 依赖下载安装更新（跨平台）
- launcher.rs — Shell命令生成与进程启动
- config_storage.rs — 项目CRUD、持久化、排序
- cc_config_checker.rs — CC配置扫描与修复
- settings_manager.rs — 旧版设置管理
- environment.rs — 环境变量工具

## 关联项目
- cc mobot (D:\cc mobot) — 编译版本（D盘根目录）
- cc capybara (D:\cc capybara) — 浏览器组件
- MobotAgentService (桌面) — Agent服务

## 备注
Tauri 2全栈桌面应用，前端React + 后端Rust，支持多种Claude Code启动模式。发布版本号v1.0.5，GitHub Releases自动构建。
