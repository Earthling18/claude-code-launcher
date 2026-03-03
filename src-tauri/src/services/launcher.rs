use std::collections::HashMap;
use std::process::Command;
#[cfg(windows)]
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
        let where_cmd = format!("where.exe {} 2>$null", cli_bin);
        let check = Command::new("powershell.exe")
            .args(&["-Command", &where_cmd])
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

        if !check.status.success() || check.stdout.is_empty() {
            let npm_list_cmd = format!("npm list -g {} --depth=0 2>$null", npm_package);
            let npm_check = Command::new("powershell.exe")
                .args(&["-Command", &npm_list_cmd])
                .creation_flags(CREATE_NO_WINDOW)
                .output()
                .map_err(|e| format!("无法检查npm包: {}", e))?;

            Self::log_line(&format!(
                "npm list -g {} exit={:?} stdout={}B stderr={}B",
                npm_package,
                npm_check.status.code(),
                npm_check.stdout.len(),
                npm_check.stderr.len()
            ));

            if !npm_check.status.success() {
                return Err(format!("{}未安装或未在PATH中。请先安装{}。", cli_label, cli_label));
            }

            // Package is installed via npm but shim files are missing.
            Self::log_line(&format!("{} not in PATH but npm package exists, attempting shim repair...", cli_bin));
            let repair = Command::new("cmd.exe")
                .args(&["/c", "npm", "install", "-g", npm_package])
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

            // Verify CLI is now findable
            let recheck = Command::new("powershell.exe")
                .args(&["-Command", &where_cmd])
                .creation_flags(CREATE_NO_WINDOW)
                .output();

            let repaired = recheck
                .as_ref()
                .map(|o| o.status.success() && !o.stdout.is_empty())
                .unwrap_or(false);

            Self::log_line(&format!("shim repair result: {}", if repaired { "OK" } else { "FAILED" }));

            if !repaired {
                return Err(format!("{}的命令文件丢失，自动修复失败。请手动运行: npm install -g {}", cli_label, npm_package));
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
                &cli_label,
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
