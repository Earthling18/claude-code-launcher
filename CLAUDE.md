---
indexed_by: xiaobai-file-index
indexed_date: "2026-02-25"
category: 开发项目
tags: [rust, tauri, react, typescript, claude-sdk]
---

# claude-code-launcher-tauri

Claude Code桌面启动器完整源码，Tauri 2应用，支持多项目管理、4种启动模式（原生/自定义/远程Bridge/Mobot）、自动更新。

## 技术栈
- Frontend: React 19 + TypeScript + Tailwind CSS + Vite
- Desktop: Tauri 2 (Rust)
- Backend: Rust + Python Bridge (FastAPI + Claude Agent SDK)
- UI: @dnd-kit, React Router
- Plugins: Clipboard, Process, Updater

## 主要内容
- src/ — React前端
  - pages/ — 页面组件
  - components/ — 通用组件
  - hooks/ — 自定义Hooks
  - types/ — TypeScript类型定义
  - api.ts — API层
  - App.tsx — 应用入口
- src-tauri/ — Rust后端
  - Cargo.toml — Rust依赖配置
  - tauri.conf.json — Tauri配置（v0.2.5）
  - resources/ — 资源文件
  - icons/ — 应用图标
- .github/ — CI/CD配置
- docs/ — 文档

## 功能特性
- 项目CRUD + 拖拽排序 + 置顶
- 4种启动模式：原生/自定义/远程Bridge/Mobot
- 远程Bridge：Python FastAPI + Claude Agent SDK，WebSocket长连接
- 远程Bridge自动获取Key：通过管理后台API自动创建/获取用户Bind Key，基于OS用户名识别
- 远程Bridge连接提示：显示可复制的 /变身 命令 + 艾灵企微二维码
- 启动桥接时自动保存配置
- 依赖检测 + 一键安装
- 自动更新（GitHub Releases）
- 新手引导
- WebView2 Runtime自动安装（embedBootstrapper，安装时自动引导用户安装WebView2）

## 关联项目
- cc mobot (D:\cc mobot) — 编译版本（D盘根目录）
- cc capybara (D:\cc capybara) — 浏览器组件
- MobotAgentService (桌面) — Agent服务

## 备注
Tauri 2全栈桌面应用，前端React + 后端Rust，支持多种Claude Code启动模式。
