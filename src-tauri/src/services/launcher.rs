use std::collections::HashMap;
use std::process::Command;
#[cfg(windows)]
use std::path::{Path, PathBuf};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

pub struct Launcher;

impl Launcher {
    fn escape_ps_single_quotes(value: &str) -> String {
        value.replace('\'', "''")
    }

    #[cfg(windows)]
    fn launcher_log_path() -> std::path::PathBuf {
        // Prefer LocalAppData so logs survive across runs and are easy to find on Windows.
        // Fallback to TEMP if LocalAppData is unavailable for some reason.
        let base = dirs::data_local_dir().unwrap_or_else(std::env::temp_dir);
        let new_dir = base.join("CCLauncher").join("logs");
        let legacy_dir = base.join("ClaudeCodeLauncher").join("logs");

        // One-time rename: legacy log dir → new dir.
        if !new_dir.exists() && legacy_dir.exists() {
            log::info!(
                "Migrating log directory: {} -> {}",
                legacy_dir.display(),
                new_dir.display()
            );
            let _ = std::fs::rename(&legacy_dir, &new_dir);
        }

        new_dir.join("launcher.log")
    }

    /// System-wide wt.exe detection, cached for the process lifetime
    /// (`where.exe` costs ~100ms per call). If the user installs WT while the
    /// launcher is running, a restart picks it up.
    #[cfg(windows)]
    fn system_wt_available() -> bool {
        use std::os::windows::process::CommandExt;
        use std::sync::OnceLock;
        static AVAILABLE: OnceLock<bool> = OnceLock::new();
        *AVAILABLE.get_or_init(|| {
            // Escape hatch for testing the bundled-WT / conhost fallback paths.
            if std::env::var("CCL_FORCE_NO_SYSTEM_WT").is_ok() {
                Self::log_line("CCL_FORCE_NO_SYSTEM_WT set: ignoring system wt.exe");
                return false;
            }
            Command::new("where.exe")
                .arg("wt.exe")
                .creation_flags(CREATE_NO_WINDOW)
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false)
        })
    }

    /// Locate the bundled Windows Terminal portable shipped under `resources\wt`
    /// next to the launcher executable (declared in tauri.windows.conf.json,
    /// populated by scripts/fetch-wt.ps1 / CI).
    #[cfg(windows)]
    fn bundled_wt_dir() -> Option<PathBuf> {
        let exe = std::env::current_exe().ok()?;
        let dir = exe.parent()?.join("resources").join("wt");
        if dir.join("WindowsTerminal.exe").exists() {
            Some(dir)
        } else {
            None
        }
    }

    /// WT only runs in portable mode (settings kept beside the exe instead of the
    /// user's profile) when a `.portable` marker sits next to WindowsTerminal.exe.
    /// Resource bundling can't be trusted to ship dotfiles, so create it on first
    /// use. If the install dir is read-only (per-machine installs), copy the whole
    /// directory to %LOCALAPPDATA%\CCLauncher\wt and run from there.
    #[cfg(windows)]
    fn prepare_bundled_wt(dir: &Path) -> Result<PathBuf, String> {
        let marker = dir.join(".portable");
        if marker.exists() || std::fs::write(&marker, b"").is_ok() {
            return Ok(dir.join("WindowsTerminal.exe"));
        }

        Self::log_line("bundled wt dir not writable; using LocalAppData copy");
        let base = dirs::data_local_dir().ok_or("无法获取LocalAppData目录")?;
        let target = base.join("CCLauncher").join("wt");
        let target_exe = target.join("WindowsTerminal.exe");
        if !target_exe.exists() {
            Self::copy_dir_recursive(dir, &target)
                .map_err(|e| format!("复制内置Windows Terminal失败: {}", e))?;
        }
        std::fs::write(target.join(".portable"), b"")
            .map_err(|e| format!("创建.portable标记失败: {}", e))?;
        Ok(target_exe)
    }

    #[cfg(windows)]
    fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
        std::fs::create_dir_all(dst)?;
        for entry in std::fs::read_dir(src)? {
            let entry = entry?;
            let to = dst.join(entry.file_name());
            if entry.file_type()?.is_dir() {
                Self::copy_dir_recursive(&entry.path(), &to)?;
            } else {
                std::fs::copy(entry.path(), &to)?;
            }
        }
        Ok(())
    }

    /// Spawn a PowerShell session inside Windows Terminal (system wt.exe or the
    /// bundled WindowsTerminal.exe — both accept the same command line).
    #[cfg(windows)]
    fn spawn_in_wt(program: &Path, work_dir: &str, title: &str, encoded: &str) -> std::io::Result<()> {
        use std::os::windows::process::CommandExt;
        Command::new(program)
            .args(&[
                "new-tab",
                "--title",
                title,
                "-d",
                work_dir,
                "powershell.exe",
                "-NoExit",
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map(|_| ())
    }

    #[cfg(windows)]
    fn launcher_transcript_path() -> std::path::PathBuf {
        let mut p = Self::launcher_log_path();
        p.set_file_name("powershell-transcript.log");
        p
    }

    #[cfg(windows)]
    fn launcher_run_log_path() -> std::path::PathBuf {
        let mut p = Self::launcher_log_path();
        p.set_file_name("claude-run.log");
        p
    }

    #[cfg(windows)]
    fn log_line(line: &str) {
        use std::fs::OpenOptions;
        use std::io::Write;

        let path = Self::launcher_log_path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }

        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(&path) {
            let _ = writeln!(f, "[{}] {}", ts, line);
        }
    }

    /// Internal config keys that are NOT environment variables
    const INTERNAL_KEYS: &'static [&'static str] = &["SKIP_PERMISSIONS", "CLI_COMMAND"];

    /// Sensitive env var keys whose values should be redacted in logs
    const SENSITIVE_KEYS: &'static [&'static str] = &["ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"];

    /// Build the CLI launch command string from config map.
    /// Reads CLI_COMMAND (default "claude") and SKIP_PERMISSIONS to determine the command.
    fn build_cli_command(config: &HashMap<String, String>) -> String {
        let cli = config.get("CLI_COMMAND").map(|s| s.as_str()).unwrap_or("claude");
        let skip_permissions = config.get("SKIP_PERMISSIONS").map(|v| v == "true").unwrap_or(false);

        if skip_permissions {
            // For codex, use --yolo; for claude, use --dangerously-skip-permissions
            if cli.starts_with("codex") {
                format!("{} --yolo", cli)
            } else {
                format!("{} --dangerously-skip-permissions", cli)
            }
        } else {
            cli.to_string()
        }
    }

    /// Collect env var keys from config (excluding internal keys), preserving a stable order.
    fn env_keys_from_config(config: &HashMap<String, String>) -> Vec<String> {
        // Preferred order for well-known keys, then any remaining keys sorted
        let preferred_order = [
            "ANTHROPIC_MODEL",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_BASE_URL",
            "OPENAI_API_KEY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
        ];
        let mut keys = Vec::new();
        for &k in preferred_order.iter() {
            if config.contains_key(k) {
                keys.push(k.to_string());
            }
        }
        // Add any remaining keys not in preferred_order and not internal
        let mut remaining: Vec<String> = config.keys()
            .filter(|k| !preferred_order.contains(&k.as_str()) && !Self::INTERNAL_KEYS.contains(&k.as_str()))
            .cloned()
            .collect();
        remaining.sort();
        keys.extend(remaining);
        keys
    }

    #[cfg(windows)]
    fn sanitize_command_for_log(command: &str) -> String {
        // Avoid writing secrets into logs. We only redact known sensitive env vars.
        // The current command format uses single quotes: $env:KEY='value'.
        let mut out = command.to_string();
        for key in Self::SENSITIVE_KEYS {
            let needle = format!("$env:{}='", key);
            let mut search_from = 0usize;
            while let Some(start) = out[search_from..].find(&needle) {
                let start = search_from + start + needle.len();
                if let Some(end_rel) = out[start..].find('\'') {
                    let end = start + end_rel;
                    out.replace_range(start..end, "<redacted>");
                    search_from = start + "<redacted>".len() + 1;
                } else {
                    break;
                }
            }
        }
        out
    }

    #[cfg(windows)]
    fn encode_powershell_encoded_command(command: &str) -> String {
        // PowerShell's -EncodedCommand expects UTF-16LE bytes, Base64-encoded.
        use base64::{engine::general_purpose, Engine as _};

        let mut bytes = Vec::with_capacity(command.len() * 2);
        for unit in command.encode_utf16() {
            bytes.extend_from_slice(&unit.to_le_bytes());
        }

        general_purpose::STANDARD.encode(bytes)
    }

    pub fn launch_with_config(config: HashMap<String, String>) -> Result<(), String> {
        Self::launch_with_temp_env(config, None)
    }

    pub fn launch_with_config_and_dir(config: HashMap<String, String>, working_dir: Option<String>) -> Result<(), String> {
        Self::launch_with_temp_env(config, working_dir)
    }

    pub fn launch_simple() -> Result<(), String> {
        #[cfg(windows)]
        {
            Self::execute_windows("claude", None)
        }
        #[cfg(target_os = "macos")]
        {
            Self::execute_macos("claude", None)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    fn launch_with_temp_env(config: HashMap<String, String>, working_dir: Option<String>) -> Result<(), String> {
        let env_keys = Self::env_keys_from_config(&config);
        let cli_cmd = Self::build_cli_command(&config);

        #[cfg(windows)]
        {
            let mut commands = Vec::new();
            for key in env_keys.iter() {
                if let Some(value) = config.get(key.as_str()) {
                    if !value.is_empty() {
                        let escaped_value = Self::escape_ps_single_quotes(value);
                        commands.push(format!("$env:{}='{}'", key, escaped_value));
                    }
                }
            }
            commands.push(cli_cmd);
            let full_command = commands.join("; ");
            Self::execute_windows(&full_command, working_dir)
        }

        #[cfg(target_os = "macos")]
        {
            let mut env_exports = Vec::new();
            for key in env_keys.iter() {
                if let Some(value) = config.get(key.as_str()) {
                    if !value.is_empty() {
                        let escaped_value = value.replace("\"", "\\\"");
                        env_exports.push(format!("export {}=\"{}\"", key, escaped_value));
                    }
                }
            }
            env_exports.push(cli_cmd);
            let full_command = env_exports.join(" && ");
            Self::execute_macos(&full_command, working_dir)
        }

        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    /// Locate the npm package dir behind a resolved shim and return the first
    /// truncated/corrupted native exe inside it, if any. An interrupted update
    /// can leave e.g. claude-code's ~250MB bin/claude.exe half-written; the
    /// shim still resolves, so `where.exe` alone cannot catch this.
    #[cfg(windows)]
    fn find_corrupted_package_exe(where_stdout: &[u8], npm_package: &str) -> Option<PathBuf> {
        use super::installer::Installer;
        let shim_lines = String::from_utf8_lossy(where_stdout);
        let shim = PathBuf::from(shim_lines.lines().next()?.trim());
        let mut pkg_dir = shim.parent()?.join("node_modules");
        for part in npm_package.split('/') {
            pkg_dir.push(part);
        }
        // Not the npm-shim layout (e.g. native installer on PATH) — nothing to check.
        if !pkg_dir.is_dir() {
            return None;
        }
        let mut exes = Vec::new();
        Installer::collect_package_exes(&pkg_dir, 0, &mut exes);
        exes.into_iter().find(|e| Installer::exe_corrupted(e))
    }

    #[cfg(windows)]
    fn execute_windows(command: &str, working_dir: Option<String>) -> Result<(), String> {
        use std::os::windows::process::CommandExt;

        Self::log_line("=== launch start ===");
        Self::log_line(&format!("raw command: {}", Self::sanitize_command_for_log(command)));
        if let Some(ref wd) = working_dir {
            Self::log_line(&format!("working_dir arg: {}", wd));
        } else {
            Self::log_line("working_dir arg: <none>");
        }

        // GUI apps can have a stale PATH after installs; refresh from registry so CLI tools are discoverable.
        super::dependency_checker::DependencyChecker::refresh_system_path();
        Self::log_line(&format!("PATH len: {}", std::env::var("PATH").unwrap_or_default().len()));

        // Determine CLI binary name from the command string.
        // Command format: "$env:KEY='val'; $env:KEY2='val2'; codex --yolo"
        // Split by ';', take the last segment (the CLI command), then extract the first word.
        let cli_bin = command.split(';')
            .map(|s| s.trim())
            .filter(|s| !s.is_empty() && !s.starts_with("$env:"))
            .last()
            .and_then(|s| s.split_whitespace().next())
            .unwrap_or("claude");

        let (npm_package, cli_label) = if cli_bin == "codex" {
            ("@openai/codex", "Codex CLI")
        } else {
            ("@anthropic-ai/claude-code", "Claude Code")
        };

        // First check if CLI command exists
        let check = Command::new("where.exe")
            .arg(cli_bin)
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .map_err(|e| format!("无法检查{}命令: {}", cli_label, e))?;

        Self::log_line(&format!(
            "where.exe {} exit={:?} stdout={}B stderr={}B",
            cli_bin,
            check.status.code(),
            check.stdout.len(),
            check.stderr.len()
        ));

        let shim_missing = !check.status.success() || check.stdout.is_empty();

        // Even when the shim resolves, an interrupted update can leave the
        // package's native binary truncated (e.g. claude-code's ~250MB
        // bin/claude.exe) — Windows then fails it with the misleading
        // "不支持的 16 位应用程序" dialog. Catch that here too.
        let corrupted_exe = if shim_missing {
            None
        } else {
            Self::find_corrupted_package_exe(&check.stdout, npm_package)
        };

        if let Some(ref bad) = corrupted_exe {
            Self::log_line(&format!("{} native exe corrupted: {}", cli_bin, bad.display()));
            return Err(format!(
                "{}安装已损坏，请在依赖面板点击“重装”后再启动",
                cli_label
            ));
        }

        if shim_missing {
            let package_present =
                super::dependency_checker::DependencyChecker::npm_package_present(npm_package);
            if package_present {
                Self::log_line(&format!(
                    "{} npm package exists but shim is missing; explicit reinstall required",
                    cli_bin
                ));
                return Err(format!(
                    "{}安装已损坏，请在依赖面板点击“重装”后再启动",
                    cli_label
                ));
            }

            // The package truly is absent, so this is a first install rather
            // than a repair. Damaged installations always require Reinstall.
            Self::log_line(&format!("{} package absent, attempting first install...", cli_bin));
            let repair = Command::new("cmd.exe")
                .args(&["/c", "npm", "install", "-g", npm_package])
                .creation_flags(CREATE_NO_WINDOW)
                .output();

            match &repair {
                Ok(out) => Self::log_line(&format!(
                    "repair exit={:?} stdout={}B stderr={}B",
                    out.status.code(),
                    out.stdout.len(),
                    out.stderr.len()
                )),
                Err(e) => Self::log_line(&format!("repair failed to run: {}", e)),
            }

            // Refresh PATH again after repair
            super::dependency_checker::DependencyChecker::refresh_system_path();

            // Validate the real CLI, not just the shim. `where.exe` can pass
            // while the native binary behind the shim is truncated.
            let installed_status = if cli_bin == "codex" {
                super::dependency_checker::DependencyChecker::check_codex()
            } else {
                super::dependency_checker::DependencyChecker::check_claude()
            };
            let repaired = installed_status.installed
                && installed_status.meets_requirement
                && installed_status.error.is_none();

            Self::log_line(&format!("repair result: {}", if repaired { "OK" } else { "FAILED" }));

            if !repaired {
                if super::dependency_checker::DependencyChecker::npm_package_present(npm_package)
                {
                    return Err(format!(
                        "{}安装后仍不可用，请在依赖面板点击“重装”",
                        cli_label
                    ));
                }
                return Err(format!("{}安装失败，请在依赖面板点击“安装”", cli_label));
            }
        }

        // Determine the working directory
        let work_dir: PathBuf = if let Some(ref dir) = working_dir {
            let path = PathBuf::from(dir);
            if path.exists() && path.is_dir() {
                path
            } else {
                return Err(format!("工作目录不存在: {}", dir));
            }
        } else {
            dirs::home_dir()
                .ok_or("无法获取用户主目录".to_string())?
        };

        // Capture *all* output into a log file, but still show it in the terminal.
        //
        // Important: this app is a GUI process (no console). If we spawn PowerShell directly,
        // the child can end up without a usable stdin/tty, and `claude` will exit immediately.
        // Using `cmd.exe /c start ...` reliably creates a real console with interactive stdin.
        let transcript_path = Self::launcher_transcript_path();
        let transcript_path_str = transcript_path.to_string_lossy();
        let transcript_path_escaped = Self::escape_ps_single_quotes(&transcript_path_str);

        let run_log_path = Self::launcher_run_log_path();
        let run_log_path_str = run_log_path.to_string_lossy();
        let run_log_path_escaped = Self::escape_ps_single_quotes(&run_log_path_str);

        Self::log_line(&format!("transcript path: {}", transcript_path_str));
        Self::log_line(&format!("run log path: {}", run_log_path_str));

        // Do not pipe/redirect `claude` output here: if stdout is not a TTY,
        // Claude Code may switch to non-interactive mode and exit immediately.
        // Transcript should still capture the most useful errors without breaking TTY detection.
        let ps = format!(
            concat!(
                "$ErrorActionPreference='Continue'; ",
                "$ProgressPreference='SilentlyContinue'; ",
                "try {{ Start-Transcript -Path '{}' -Append -Force | Out-Null }} catch {{}}; ",
                "'' | Out-File -FilePath '{}' -Append -Encoding utf8; ",
                "'[launcher] ' + (Get-Date).ToString('s') + ' cwd=' + (Get-Location).Path | Out-File -FilePath '{}' -Append -Encoding utf8; ",
                "try {{ {} }} catch {{ $_ | Out-Host }}; ",
                "$ec = $LASTEXITCODE; ",
                "'[launcher] exit code: ' + $ec | Out-File -FilePath '{}' -Append -Encoding utf8; ",
                "try {{ Stop-Transcript | Out-Null }} catch {{}}; ",
                "Read-Host '[launcher] press Enter to close' | Out-Null;"
            ),
            transcript_path_escaped,
            run_log_path_escaped,
            run_log_path_escaped,
            command,
            run_log_path_escaped,
        );

        let encoded = Self::encode_powershell_encoded_command(&ps);
        Self::log_line(&format!("encoded_command length: {}", encoded.len()));

        // Prefer Windows Terminal for ANSI/TUI rendering (conhost is laggy and
        // glitchy with Claude Code). Three-tier fallback chain — a failure at any
        // tier logs and falls through to the next, never aborts the launch:
        //   1. system wt.exe
        //   2. bundled WT portable (resources\wt, Windows-only)
        //   3. conhost via cmd.exe /c start
        let work_dir_str = work_dir.to_string_lossy();
        let mut launched_in_wt = false;

        if Self::system_wt_available() {
            match Self::spawn_in_wt(Path::new("wt.exe"), &work_dir_str, cli_label, &encoded) {
                Ok(()) => {
                    Self::log_line("spawned system wt.exe OK");
                    launched_in_wt = true;
                }
                Err(e) => {
                    Self::log_line(&format!("spawn system wt.exe failed, falling back: {}", e))
                }
            }
        } else {
            Self::log_line("system wt.exe not found");
        }

        if !launched_in_wt {
            if let Some(dir) = Self::bundled_wt_dir() {
                match Self::prepare_bundled_wt(&dir) {
                    Ok(exe) => {
                        match Self::spawn_in_wt(&exe, &work_dir_str, cli_label, &encoded) {
                            Ok(()) => {
                                Self::log_line(&format!("spawned bundled wt OK: {}", exe.display()));
                                launched_in_wt = true;
                            }
                            Err(e) => Self::log_line(&format!(
                                "spawn bundled wt failed, falling back to conhost: {}",
                                e
                            )),
                        }
                    }
                    Err(e) => Self::log_line(&format!(
                        "prepare bundled wt failed, falling back to conhost: {}",
                        e
                    )),
                }
            } else {
                Self::log_line("bundled wt not present");
            }
        }

        if !launched_in_wt {
            Command::new("cmd.exe")
                .current_dir(&work_dir)
                .args(&[
                    "/c",
                    "start",
                    cli_label,
                    "powershell.exe",
                    "-NoExit",
                    "-NoLogo",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    &encoded,
                ])
                // Hide the intermediate `cmd.exe` window; `start` will create the visible PowerShell window.
                .creation_flags(CREATE_NO_WINDOW)
                .spawn()
                .map_err(|e| {
                    Self::log_line(&format!("spawn cmd.exe failed: {}", e));
                    format!("无法启动CMD: {}", e)
                })?;
            Self::log_line("spawned cmd.exe start OK");
        }
        Self::log_line("=== launch end ===");
        Ok(())
    }

    #[cfg(target_os = "macos")]
    fn execute_macos(command: &str, working_dir: Option<String>) -> Result<(), String> {
        // Pre-check CLI usability. Existing-but-broken packages must be
        // explicitly reinstalled; a plain npm install often leaves the broken
        // shim/link untouched.
        {
            let (cli_bin, npm_package, cli_label) = if command.contains("codex") {
                ("codex", "@openai/codex", "Codex CLI")
            } else {
                ("claude", "@anthropic-ai/claude-code", "Claude Code")
            };

            let extended_path = super::dependency_checker::get_macos_extended_path();

            let cli_ok = Command::new("sh")
                .args(&[
                    "-c",
                    &format!("PATH='{}' {} --version", extended_path, cli_bin),
                ])
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false);

            if !cli_ok {
                let package_present =
                    super::dependency_checker::DependencyChecker::npm_package_present(npm_package);
                if package_present {
                    return Err(format!(
                        "{}安装已损坏，请在依赖面板点击“重装”后再启动",
                        cli_label
                    ));
                }

                let npm_available = Command::new("sh")
                    .args(&["-c", &format!("PATH='{}' which npm", extended_path)])
                    .output()
                    .map(|o| o.status.success())
                    .unwrap_or(false);

                if npm_available {
                    eprintln!(
                        "[launcher] macOS: {} package absent, attempting first install...",
                        cli_bin
                    );
                    let install = Command::new("sh")
                        .args(&["-c", &format!("PATH='{}' npm install -g {}", extended_path, npm_package)])
                        .output();
                    let installed = install
                        .as_ref()
                        .map(|output| output.status.success())
                        .unwrap_or(false);
                    if !installed {
                        return Err(format!(
                            "{}安装失败，请在依赖面板点击“安装”",
                            cli_label
                        ));
                    }

                    let recheck = Command::new("sh")
                        .args(&[
                            "-c",
                            &format!("PATH='{}' {} --version", extended_path, cli_bin),
                        ])
                        .output()
                        .map(|output| output.status.success())
                        .unwrap_or(false);
                    if !recheck {
                        return Err(format!(
                            "{}安装后仍不可用，请在依赖面板点击“重装”",
                            cli_label
                        ));
                    }
                } else {
                    return Err("未找到 npm，请先安装 Node.js".to_string());
                }
            }
        }

        let target_dir = working_dir.unwrap_or_else(|| {
            dirs::home_dir()
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_else(|| "~".to_string())
        });

        // Determine startup message based on CLI tool
        let startup_msg = if command.contains("codex") {
            "Starting Codex..."
        } else {
            "Starting Claude Code..."
        };

        // Use osascript to open Terminal.app with the command
        // Terminal.app runs as a login shell by default, so PATH will be correct
        let script = format!(
            r#"tell application "Terminal"
                activate
                do script "cd '{}' && echo '{}' && {}"
            end tell"#,
            target_dir.replace("'", "'\\''"),
            startup_msg,
            command.replace("\"", "\\\"")
        );

        Command::new("osascript")
            .args(&["-e", &script])
            .spawn()
            .map_err(|e| format!("无法启动Terminal: {}", e))?;

        Ok(())
    }

    // Windows: PowerShell command
    pub fn generate_powershell_command(config: &HashMap<String, String>) -> String {
        Self::generate_powershell_command_with_dir(config, None)
    }

    pub fn generate_powershell_command_with_dir(config: &HashMap<String, String>, working_dir: Option<String>) -> String {
        let mut commands = Vec::new();
        let env_keys = Self::env_keys_from_config(config);

        // Add cd command if working directory specified
        if let Some(dir) = working_dir {
            let escaped_dir = Self::escape_ps_single_quotes(&dir);
            commands.push(format!("Set-Location -LiteralPath '{}'", escaped_dir));
        }

        for key in env_keys.iter() {
            if let Some(value) = config.get(key.as_str()) {
                if !value.is_empty() {
                    let escaped_value = Self::escape_ps_single_quotes(value);
                    commands.push(format!("$env:{}='{}'", key, escaped_value));
                }
            }
        }

        commands.push(Self::build_cli_command(config));
        commands.join("; ")
    }

    // Windows: CMD command
    pub fn generate_cmd_command(config: &HashMap<String, String>) -> String {
        Self::generate_cmd_command_with_dir(config, None)
    }

    pub fn generate_cmd_command_with_dir(config: &HashMap<String, String>, working_dir: Option<String>) -> String {
        let mut commands = Vec::new();
        let env_keys = Self::env_keys_from_config(config);

        // Add cd command if working directory specified
        if let Some(dir) = working_dir {
            commands.push(format!("cd /d \"{}\"", dir));
        }

        for key in env_keys.iter() {
            if let Some(value) = config.get(key.as_str()) {
                if !value.is_empty() {
                    let escaped = if value.contains(' ') || value.contains('&') || value.contains('|') || value.contains('"') {
                        value.replace("\"", "\"\"")
                    } else {
                        value.clone()
                    };
                    commands.push(format!("set {}={}", key, escaped));
                }
            }
        }

        commands.push(Self::build_cli_command(config));
        commands.join(" & ")
    }

    // macOS/Linux: Bash command
    pub fn generate_bash_command(config: &HashMap<String, String>) -> String {
        Self::generate_bash_command_with_dir(config, None)
    }

    pub fn generate_bash_command_with_dir(config: &HashMap<String, String>, working_dir: Option<String>) -> String {
        let mut commands = Vec::new();
        let env_keys = Self::env_keys_from_config(config);

        // Add cd command if working directory specified
        if let Some(dir) = working_dir {
            commands.push(format!("cd '{}'", dir.replace("'", "'\\''")));
        }

        for key in env_keys.iter() {
            if let Some(value) = config.get(key.as_str()) {
                if !value.is_empty() {
                    let escaped_value = value.replace("\"", "\\\"");
                    commands.push(format!("export {}=\"{}\"", key, escaped_value));
                }
            }
        }

        commands.push(Self::build_cli_command(config));
        commands.join(" && ")
    }
}

#[cfg(all(test, windows))]
mod corrupted_exe_tests {
    use super::Launcher;

    #[test]
    fn finds_corrupted_exe_behind_resolved_shim() {
        let root = std::env::temp_dir().join(format!("ccl-shim-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let pkg_bin = root
            .join("node_modules")
            .join("@anthropic-ai")
            .join("claude-code")
            .join("bin");
        std::fs::create_dir_all(&pkg_bin).unwrap();
        let shim = root.join("claude.cmd");
        std::fs::write(&shim, "@echo off").unwrap();
        // where.exe output: shim path + CRLF, possibly more lines
        let where_out = format!("{}\r\n{}\r\n", shim.display(), root.join("claude").display()).into_bytes();
        let exe = pkg_bin.join("claude.exe");

        std::fs::write(&exe, b"").unwrap(); // truncated by an interrupted update
        let found = Launcher::find_corrupted_package_exe(&where_out, "@anthropic-ai/claude-code");
        assert_eq!(found.as_deref(), Some(exe.as_path()));

        std::fs::write(&exe, b"MZ\x90\x00rest").unwrap(); // healthy binary
        assert!(Launcher::find_corrupted_package_exe(&where_out, "@anthropic-ai/claude-code").is_none());

        // Non-npm layout (e.g. native installer on PATH): no package dir → no check
        let bare = format!("{}\r\n", root.join("elsewhere").join("claude.exe").display()).into_bytes();
        assert!(Launcher::find_corrupted_package_exe(&bare, "@anthropic-ai/claude-code").is_none());

        let _ = std::fs::remove_dir_all(&root);
    }
}
