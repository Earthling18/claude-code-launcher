# Windows Terminal Portable（占位目录）

此目录在构建时由 `scripts/fetch-wt.ps1`（本地）或 CI（`.github/workflows/build.yml`）填充
微软官方 Windows Terminal Portable 发行版（MIT 协议），作为启动 Claude Code 时
系统没有 wt.exe 的回退终端，避免落到 conhost（卡顿/花屏/缩放闪退）。

- 请勿向此目录提交任何二进制文件（.gitignore 已排除）。
- 本地开发若不需要测试 bundled WT 路径，可忽略此目录——构建不依赖其内容，
  此 README 仅用于保证 `tauri.windows.conf.json` 中的 resources glob 永远非空。
- 运行时逻辑见 `src-tauri/src/services/launcher.rs` 的 `bundled_wt_dir` / `prepare_bundled_wt`。
