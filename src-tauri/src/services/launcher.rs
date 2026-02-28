use std::collections::HashMap;
use std::process::Command;
use std::path::PathBuf;

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
        base.join("ClaudeCodeLauncher").join("logs").join("launcher.log")
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

    #[cfg(windows)]
    fn sanitize_command_for_log(command: &str) -> String {
        // Avoid writing secrets into logs. We only redact known sensitive env vars.
        // The current command format uses single quotes: $env:KEY='value'.
        let mut out = command.to_string();
        for key in ["ANTHROPIC_AUTH_TOKEN"] {
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
        let ordered_keys = [
            "ANTHROPIC_MODEL",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "HTTP_PROXY",
            "HTTPS_PROXY",
        ];

        let skip_permissions = config.get("SKIP_PERMISSIONS").map(|v| v == "true").unwrap_or(false);
        let claude_cmd = if skip_permissions {
            "claude --dangerously-skip-permissions"
        } else {
            "claude"
        };

        #[cfg(windows)]
        {
            let mut commands = Vec::new();
            for key in ordered_keys.iter() {
                if let Some(value) = config.get(*key) {
                    if !value.is_empty() {
                        let escaped_value = Self::escape_ps_single_quotes(value);
                        commands.push(format!("$env:{}='{}'", key, escaped_value));
                    }
                }
            }
            commands.push(claude_cmd.to_string());
            let full_command = commands.join("; ");
            Self::execute_windows(&full_command, working_dir)
        }

        #[cfg(target_os = "macos")]
        {
            let mut env_exports = Vec::new();
            for key in ordered_keys.iter() {
                if let Some(value) = config.get(*key) {
                    if !value.is_empty() {
                        let escaped_value = value.replace("\"", "\\\"");
                        env_exports.push(format!("export {}=\"{}\"", key, escaped_value));
                    }
                }
            }
            env_exports.push(claude_cmd.to_string());
            let full_command = env_exports.join(" && ");
            Self::execute_macos(&full_command, working_dir)
        }

        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    #[cfg(windows)]
    fn execute_windows(command: &str, working_dir: Option<String>) -> Result<(), String> {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        Self::log_line("=== launch start ===");
        Self::log_line(&format!("raw command: {}", Self::sanitize_command_for_log(command)));
        if let Some(ref wd) = working_dir {
            Self::log_line(&format!("working_dir arg: {}", wd));
        } else {
            Self::log_line("working_dir arg: <none>");
        }

        // GUI apps can have a stale PATH after installs; refresh from registry so `claude` is discoverable.
        super::dependency_checker::DependencyChecker::refresh_system_path();
        Self::log_line(&format!("PATH len: {}", std::env::var("PATH").unwrap_or_default().len()));

        // First check if claude command exists
        let check = Command::new("powershell.exe")
            .args(&["-Command", "where.exe claude 2>$null"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .map_err(|e| format!("无法检查Claude命令: {}", e))?;

        Self::log_line(&format!(
            "where.exe claude exit={:?} stdout={}B stderr={}B",
            check.status.code(),
            check.stdout.len(),
            check.stderr.len()
        ));

        if !check.status.success() || check.stdout.is_empty() {
            let npm_check = Command::new("powershell.exe")
                .args(&["-Command", "npm list -g @anthropic-ai/claude-code --depth=0 2>$null"])
                .creation_flags(CREATE_NO_WINDOW)
                .output()
                .map_err(|e| format!("无法检查npm包: {}", e))?;

            Self::log_line(&format!(
                "npm list -g @anthropic-ai/claude-code exit={:?} stdout={}B stderr={}B",
                npm_check.status.code(),
                npm_check.stdout.len(),
                npm_check.stderr.len()
            ));

            if !npm_check.status.success() {
                return Err("Claude Code未安装或未在PATH中。请先安装Claude Code。".to_string());
            }

            // Package is installed via npm but shim files (claude.cmd) are missing.
            // This can happen after node/npm upgrades or npm global rebuilds.
            // Auto-repair by re-installing to recreate the shim files.
            Self::log_line("claude not in PATH but npm package exists, attempting shim repair...");
            let repair = Command::new("cmd.exe")
                .args(&["/c", "npm", "install", "-g", "@anthropic-ai/claude-code"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();

            match &repair {
                Ok(out) => Self::log_line(&format!(
                    "shim repair exit={:?} stdout={}B stderr={}B",
                    out.status.code(),
                    out.stdout.len(),
                    out.stderr.len()
                )),
                Err(e) => Self::log_line(&format!("shim repair failed to run: {}", e)),
            }

            // Refresh PATH again after repair
            super::dependency_checker::DependencyChecker::refresh_system_path();

            // Verify claude is now findable
            let recheck = Command::new("powershell.exe")
                .args(&["-Command", "where.exe claude 2>$null"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();

            let repaired = recheck
                .as_ref()
                .map(|o| o.status.success() && !o.stdout.is_empty())
                .unwrap_or(false);

            Self::log_line(&format!("shim repair result: {}", if repaired { "OK" } else { "FAILED" }));

            if !repaired {
                return Err("Claude Code的命令文件丢失，自动修复失败。请手动运行: npm install -g @anthropic-ai/claude-code".to_string());
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

        // Start a new console window and keep it open for interactive use and debugging.
        Command::new("cmd.exe")
            .current_dir(&work_dir)
            .args(&[
                "/c",
                "start",
                "Claude Code",
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
        Self::log_line("=== launch end ===");
        Ok(())
    }

    #[cfg(target_os = "macos")]
    fn execute_macos(command: &str, working_dir: Option<String>) -> Result<(), String> {
        // Note: We don't check for claude existence here because:
        // 1. Terminal.app will launch with a login shell that loads .zshrc/.bash_profile
        // 2. This means PATH will include npm global bin, homebrew, nvm, etc.
        // 3. The GUI app doesn't have this PATH, so `which claude` would fail even when claude is installed
        // 4. If claude is not installed, the user will see the error directly in Terminal

        let target_dir = working_dir.unwrap_or_else(|| {
            dirs::home_dir()
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_else(|| "~".to_string())
        });

        // Use osascript to open Terminal.app with the command
        // Terminal.app runs as a login shell by default, so PATH will be correct
        let script = format!(
            r#"tell application "Terminal"
                activate
                do script "cd '{}' && echo 'Starting Claude Code...' && {}"
            end tell"#,
            target_dir.replace("'", "'\\''"),
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
        let ordered_keys = [
            "ANTHROPIC_MODEL",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "HTTP_PROXY",
            "HTTPS_PROXY",
        ];

        // Add cd command if working directory specified
        if let Some(dir) = working_dir {
            let escaped_dir = Self::escape_ps_single_quotes(&dir);
            commands.push(format!("Set-Location -LiteralPath '{}'", escaped_dir));
        }

        for key in ordered_keys.iter() {
            if let Some(value) = config.get(*key) {
                if !value.is_empty() {
                    let escaped_value = Self::escape_ps_single_quotes(value);
                    commands.push(format!("$env:{}='{}'", key, escaped_value));
                }
            }
        }

        let claude_cmd = if config.get("SKIP_PERMISSIONS").map(|v| v == "true").unwrap_or(false) {
            "claude --dangerously-skip-permissions".to_string()
        } else {
            "claude".to_string()
        };
        commands.push(claude_cmd);
        commands.join("; ")
    }

    // Windows: CMD command
    pub fn generate_cmd_command(config: &HashMap<String, String>) -> String {
        Self::generate_cmd_command_with_dir(config, None)
    }

    pub fn generate_cmd_command_with_dir(config: &HashMap<String, String>, working_dir: Option<String>) -> String {
        let mut commands = Vec::new();
        let ordered_keys = [
            "ANTHROPIC_MODEL",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "HTTP_PROXY",
            "HTTPS_PROXY",
        ];

        // Add cd command if working directory specified
        if let Some(dir) = working_dir {
            commands.push(format!("cd /d \"{}\"", dir));
        }

        for key in ordered_keys.iter() {
            if let Some(value) = config.get(*key) {
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

        let claude_cmd = if config.get("SKIP_PERMISSIONS").map(|v| v == "true").unwrap_or(false) {
            "claude --dangerously-skip-permissions".to_string()
        } else {
            "claude".to_string()
        };
        commands.push(claude_cmd);
        commands.join(" & ")
    }

    // macOS/Linux: Bash command
    pub fn generate_bash_command(config: &HashMap<String, String>) -> String {
        Self::generate_bash_command_with_dir(config, None)
    }

    pub fn generate_bash_command_with_dir(config: &HashMap<String, String>, working_dir: Option<String>) -> String {
        let mut commands = Vec::new();
        let ordered_keys = [
            "ANTHROPIC_MODEL",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "HTTP_PROXY",
            "HTTPS_PROXY",
        ];

        // Add cd command if working directory specified
        if let Some(dir) = working_dir {
            commands.push(format!("cd '{}'", dir.replace("'", "'\\''")));
        }

        for key in ordered_keys.iter() {
            if let Some(value) = config.get(*key) {
                if !value.is_empty() {
                    let escaped_value = value.replace("\"", "\\\"");
                    commands.push(format!("export {}=\"{}\"", key, escaped_value));
                }
            }
        }

        let claude_cmd = if config.get("SKIP_PERMISSIONS").map(|v| v == "true").unwrap_or(false) {
            "claude --dangerously-skip-permissions".to_string()
        } else {
            "claude".to_string()
        };
        commands.push(claude_cmd);
        commands.join(" && ")
    }
}
