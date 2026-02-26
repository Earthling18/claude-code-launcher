use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::io::{BufRead, BufReader, Read as IoRead};

use once_cell::sync::Lazy;

use crate::commands::bridge_admin_config;
use crate::models::ProjectConfig;

const MAX_LOG_LINES: usize = 200;

/// Bridge process group: agent_server (Python FastAPI) + bridge_client (Python)
struct BridgeProcessGroup {
    agent_server: Child,
    bridge_client: Child,
    started_at: u64,
    agent_port: u16,
    logs: VecDeque<String>,
}

/// Bridge status returned to frontend
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BridgeStatus {
    pub running: bool,
    pub agent_ok: bool,
    pub client_connected: bool,
    pub started_at: Option<u64>,
    pub agent_port: Option<u16>,
}

static BRIDGES: Lazy<Mutex<HashMap<String, BridgeProcessGroup>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

pub struct BridgeManager;

impl BridgeManager {
    /// Resolve bridge directory (handles dev mode fallback)
    fn resolve_bridge_dir(resource_dir: &str) -> Result<PathBuf, String> {
        // Strip Windows \\?\ extended path prefix — it can cause issues with some APIs
        let resource_dir = resource_dir.strip_prefix(r"\\?\").unwrap_or(resource_dir);

        // Tauri 2 resource_dir() returns the install root; resources are under resources/ subdir
        let bridge_dir = Path::new(resource_dir).join("resources").join("bridge");
        let bridge_dir = if !bridge_dir.join("app").exists() {
            // Fallback: try without resources/ prefix (dev mode or different layout)
            let alt = Path::new(resource_dir).join("bridge");
            if alt.join("app").exists() {
                alt
            } else {
                // Dev mode: use CARGO_MANIFEST_DIR
                let dev_dir = Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("resources")
                    .join("bridge");
                if dev_dir.join("app").exists() {
                    dev_dir
                } else {
                    bridge_dir
                }
            }
        } else {
            bridge_dir
        };

        if !bridge_dir.join("app").exists() {
            return Err(format!("Python app/ directory not found at: {}", bridge_dir.display()));
        }
        if !bridge_dir.join("bridge").join("bridge_clientv2.py").exists() {
            return Err(format!("bridge_clientv2.py not found at: {}", bridge_dir.display()));
        }

        Ok(bridge_dir)
    }

    /// Prepare Python environment (embedded Python + offline wheel install).
    /// Fast even on first run (~seconds). Call BEFORE start_bridge.
    pub fn prepare_env(resource_dir: &str) -> Result<String, String> {
        let bridge_dir = Self::resolve_bridge_dir(resource_dir)?;
        let agent_dir = Self::get_agent_data_dir();

        // Initialize agent directory (copy defaults)
        Self::init_agent_directory(&agent_dir, &bridge_dir)?;

        // Setup embedded Python and install wheels
        let python_exe = Self::ensure_python_env(&agent_dir, &bridge_dir)?;

        Ok(python_exe)
    }

    /// Start bridge for a project.
    /// Assumes prepare_env has been called (venv exists).
    pub fn start_bridge(
        project_id: &str,
        config: &ProjectConfig,
        resource_dir: &str,
    ) -> Result<(), String> {
        // --- Do all prep work OUTSIDE the lock ---
        let bridge_dir = Self::resolve_bridge_dir(resource_dir)?;
        let agent_dir = Self::get_agent_data_dir();

        // Init directory if needed (fast, just checks .env exists)
        Self::init_agent_directory(&agent_dir, &bridge_dir)?;

        // Check Python env - if not ready, return helpful error
        let python_exe = Self::check_python_env(&agent_dir)?;

        // Write .pth file so embedded Python can find the app module.
        // Embedded Python ignores PYTHONPATH; .pth files in site-packages are the correct way.
        let pth_file = agent_dir.join("python").join("Lib").join("site-packages").join("bridge.pth");
        std::fs::write(&pth_file, bridge_dir.to_string_lossy().as_bytes())
            .map_err(|e| format!("Failed to write bridge.pth: {}", e))?;

        let port = config.bridge_agent_port;

        // --- Now acquire lock only for process management ---
        let mut bridges = BRIDGES.lock().map_err(|e| format!("Lock error: {}", e))?;

        // If already running, stop first
        if let Some(mut group) = bridges.remove(project_id) {
            Self::kill_group(&mut group);
        }

        // Release lock briefly to avoid holding it during process spawn
        drop(bridges);

        // Kill any leftover process on the target port (from a previous crash or unclean shutdown)
        Self::kill_process_on_port(port);

        // 3. Start Agent Server (Python FastAPI via uvicorn)
        let mut agent_cmd = Command::new(&python_exe);

        agent_cmd
            .arg("-u")  // Unbuffered output so logs appear in real-time
            .arg("-m")
            .arg("uvicorn")
            .arg("app.main:app")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&agent_dir)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")  // Force UTF-8 everywhere (prevents GBK decode errors on Chinese Windows)
            .env("WECOM_PORT", port.to_string())
            .env("WECOM_HOST", "127.0.0.1");

        // Clear ALL inherited system proxy vars — agent server itself (sendMsg, COS etc.)
        // should never use proxy. Only the Claude CLI subprocess gets proxy via SDK options.env.
        agent_cmd.env("HTTP_PROXY", "");
        agent_cmd.env("HTTPS_PROXY", "");
        agent_cmd.env("http_proxy", "");
        agent_cmd.env("https_proxy", "");
        agent_cmd.env("ALL_PROXY", "");
        agent_cmd.env("all_proxy", "");

        // Inject service configs from compiled bridge_admin.json (not in source code)
        let svc_cfg = bridge_admin_config();
        agent_cmd.env("WECOM_SENDMSG_API_URL", &svc_cfg.sendmsg_api_url);
        agent_cmd.env("WECOM_SENDMSG_AUTH_KEY", &svc_cfg.sendmsg_auth_key);
        agent_cmd.env("WECOM_SENDMSG_DEP_USER_ID", &svc_cfg.sendmsg_dep_user_id);
        agent_cmd.env("WECOM_COS_API_BASE", &svc_cfg.cos_api_base);

        // Auth mode and model config via environment variables.
        if config.bridge_agent_mode == "claude" {
            agent_cmd.env("WECOM_CLAUDE_AUTH_MODE", "oauth");
            agent_cmd.env("WECOM_CLAUDE_API_BASE", "");
            agent_cmd.env("WECOM_CLAUDE_API_KEY", "");
            // Pass proxy via WECOM_HTTP_PROXY only — agent_service.py will forward
            // it to the Claude CLI subprocess via SDK options.env (not os.environ).
            agent_cmd.env("WECOM_HTTP_PROXY", if config.proxy.is_empty() { "" } else { &config.proxy });
        } else {
            // Custom mode: internal proxy gateway, no proxy needed
            agent_cmd.env("WECOM_CLAUDE_AUTH_MODE", "proxy");
            agent_cmd.env("WECOM_CLAUDE_API_BASE", &config.base_url);
            agent_cmd.env("WECOM_CLAUDE_API_KEY", &config.token);
            agent_cmd.env("WECOM_CLAUDE_MODEL", &config.model);
            agent_cmd.env("WECOM_HTTP_PROXY", "");
        }

        // maxTurns via environment variable (always set, 0 means use .env/default)
        agent_cmd.env("WECOM_AGENT_MAX_TURNS", config.bridge_max_turns.to_string());

        agent_cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            agent_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let agent_server = agent_cmd
            .spawn()
            .map_err(|e| format!("Failed to start Agent Server (Python): {}", e))?;

        log::info!("Agent Server (Python) started on port {}, pid={}", port, agent_server.id());

        // 4. Build bridge client config JSON
        let client_config = serde_json::json!({
            "server_url": config.bridge_server_url,
            "bind_key": config.bridge_bind_key,
            "client_id": config.bridge_client_id,
            "http_agent_url": format!("http://127.0.0.1:{}/api/v2/chat", port),
            "http_agent_timeout": config.bridge_agent_timeout,
            "reconnect_interval": config.bridge_reconnect_interval,
            "heartbeat_interval": config.bridge_heartbeat_interval,
        });

        let client_script = bridge_dir.join("bridge").join("bridge_clientv2.py");

        // 5. Start Bridge Client (Python)
        let mut client_cmd = Command::new(&python_exe);
        client_cmd
            .arg("-u")  // Unbuffered output so logs appear in real-time
            .arg(client_script.to_string_lossy().to_string())
            .arg("--config-json")
            .arg(client_config.to_string())
            .current_dir(&agent_dir)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Bridge client connects to internal WS server — must NOT use proxy.
        // Explicitly clear proxy vars to prevent inheriting from parent process.
        client_cmd.env_remove("HTTP_PROXY");
        client_cmd.env_remove("HTTPS_PROXY");
        client_cmd.env_remove("http_proxy");
        client_cmd.env_remove("https_proxy");
        client_cmd.env_remove("ALL_PROXY");
        client_cmd.env_remove("all_proxy");
        client_cmd.env_remove("NO_PROXY");
        client_cmd.env_remove("no_proxy");

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            client_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let bridge_client = client_cmd
            .spawn()
            .map_err(|e| format!("Failed to start Bridge Client (Python): {}", e))?;

        log::info!("Bridge Client (Python) started, pid={}", bridge_client.id());

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        let group = BridgeProcessGroup {
            agent_server,
            bridge_client,
            started_at: now,
            agent_port: port,
            logs: VecDeque::with_capacity(MAX_LOG_LINES),
        };

        // Re-acquire lock to insert the new group
        let mut bridges = BRIDGES.lock().map_err(|e| format!("Lock error: {}", e))?;
        bridges.insert(project_id.to_string(), group);
        drop(bridges);

        // Start log collection in background
        Self::start_log_collection(project_id);

        Ok(())
    }

    /// Stop bridge for a project
    pub fn stop_bridge(project_id: &str) -> Result<(), String> {
        let mut bridges = BRIDGES.lock().map_err(|e| format!("Lock error: {}", e))?;

        if let Some(mut group) = bridges.remove(project_id) {
            Self::kill_group(&mut group);
            log::info!("Bridge stopped for project: {}", project_id);
            Ok(())
        } else {
            Ok(()) // Already stopped
        }
    }

    /// Get bridge status for a project
    pub fn get_status(project_id: &str) -> BridgeStatus {
        let bridges = match BRIDGES.lock() {
            Ok(b) => b,
            Err(_) => {
                return BridgeStatus {
                    running: false,
                    agent_ok: false,
                    client_connected: false,
                    started_at: None,
                    agent_port: None,
                }
            }
        };

        if let Some(group) = bridges.get(project_id) {
            BridgeStatus {
                running: true,
                agent_ok: true,
                client_connected: true,
                started_at: Some(group.started_at),
                agent_port: Some(group.agent_port),
            }
        } else {
            BridgeStatus {
                running: false,
                agent_ok: false,
                client_connected: false,
                started_at: None,
                agent_port: None,
            }
        }
    }

    /// Get logs for a project
    pub fn get_logs(project_id: &str, max_lines: usize) -> Vec<String> {
        let bridges = match BRIDGES.lock() {
            Ok(b) => b,
            Err(_) => return vec![],
        };

        if let Some(group) = bridges.get(project_id) {
            let count = max_lines.min(group.logs.len());
            group.logs.iter().rev().take(count).rev().cloned().collect()
        } else {
            vec![]
        }
    }

    /// Stop all bridges (called on app exit)
    pub fn stop_all() {
        let mut bridges = match BRIDGES.lock() {
            Ok(b) => b,
            Err(_) => return,
        };

        for (project_id, mut group) in bridges.drain() {
            log::info!("Stopping bridge for project: {}", project_id);
            Self::kill_group(&mut group);
        }
    }

    /// Check if embedded Python is available in resources
    pub fn check_deps() -> Result<(), String> {
        // Embedded Python is bundled, no system dependency needed
        Ok(())
    }

    // ==================== Agent Config Helpers ====================

    /// Get agent data directory: %APPDATA%/claude-launcher/agent/ (Windows)
    /// or ~/.config/claude-launcher/agent/ (macOS/Linux)
    pub fn get_agent_data_dir() -> PathBuf {
        dirs::config_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("claude-launcher")
            .join("agent")
    }

    /// Open a file or folder in the system default application
    pub fn open_path_in_system(path: &Path) -> Result<(), String> {
        if !path.exists() {
            // For files, try to create parent dir and an empty file so user can start editing
            if let Some(parent) = path.parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            let _ = std::fs::write(path, "");
            if !path.exists() {
                return Err(format!("Path does not exist: {}", path.display()));
            }
        }

        #[cfg(windows)]
        {
            // Use ShellExecute-style open via cmd. Quote the path to handle spaces.
            let path_str = path.to_string_lossy().to_string();
            let mut cmd = Command::new("cmd");
            cmd.args(["/c", "start", "", &path_str]);
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
            }
            cmd.spawn()
                .map_err(|e| format!("Failed to open: {}", e))?;
        }
        #[cfg(target_os = "macos")]
        {
            Command::new("open")
                .arg(path)
                .spawn()
                .map_err(|e| format!("Failed to open: {}", e))?;
        }
        #[cfg(target_os = "linux")]
        {
            Command::new("xdg-open")
                .arg(path)
                .spawn()
                .map_err(|e| format!("Failed to open: {}", e))?;
        }
        Ok(())
    }

    // ==================== Private helpers ====================

    /// Kill any leftover process listening on the given port (cleanup from unclean shutdown)
    fn kill_process_on_port(port: u16) {
        #[cfg(windows)]
        {
            // Use netstat to find PID, then taskkill
            let output = Command::new("cmd")
                .args(["/C", &format!("netstat -ano | findstr \"LISTENING\" | findstr \":{port} \"")])
                .output();
            if let Ok(o) = output {
                let stdout = String::from_utf8_lossy(&o.stdout);
                for line in stdout.lines() {
                    // netstat format: "  TCP  127.0.0.1:5000  0.0.0.0:0  LISTENING  12345"
                    if let Some(pid_str) = line.split_whitespace().last() {
                        if let Ok(pid) = pid_str.parse::<u32>() {
                            if pid > 0 {
                                let _ = Command::new("taskkill")
                                    .args(["/F", "/T", "/PID", &pid.to_string()])
                                    .output();
                            }
                        }
                    }
                }
            }
        }
        #[cfg(not(windows))]
        {
            let output = Command::new("sh")
                .args(["-c", &format!("lsof -ti :{port}")])
                .output();
            if let Ok(o) = output {
                let stdout = String::from_utf8_lossy(&o.stdout);
                for pid_str in stdout.lines() {
                    if let Ok(pid) = pid_str.trim().parse::<u32>() {
                        if pid > 0 {
                            let _ = Command::new("kill").args(["-9", &pid.to_string()]).output();
                        }
                    }
                }
            }
        }
    }

    fn kill_group(group: &mut BridgeProcessGroup) {
        let _ = Self::kill_child(&mut group.bridge_client);
        let _ = Self::kill_child(&mut group.agent_server);
    }

    fn kill_child(child: &mut Child) -> Result<(), String> {
        #[cfg(windows)]
        {
            let pid = child.id();
            let output = Command::new("taskkill")
                .args(["/F", "/T", "/PID", &pid.to_string()])
                .output();
            match output {
                Ok(o) => {
                    if !o.status.success() {
                        let _ = child.kill();
                    }
                }
                Err(_) => {
                    let _ = child.kill();
                }
            }
        }
        #[cfg(not(windows))]
        {
            let _ = child.kill();
        }
        let _ = child.wait();
        Ok(())
    }

    /// Quick check if Python environment + deps are ready
    fn check_python_env(agent_dir: &Path) -> Result<String, String> {
        let venv_dir = agent_dir.join("venv");

        #[cfg(windows)]
        let python_exe = agent_dir.join("python").join("python.exe");
        #[cfg(not(windows))]
        let python_exe = venv_dir.join("bin").join("python");

        let marker = {
            #[cfg(windows)]
            { agent_dir.join("python").join(".deps_installed") }
            #[cfg(not(windows))]
            { venv_dir.join(".deps_installed") }
        };

        if !python_exe.exists() || !marker.exists() {
            return Err("Python environment not ready. Please wait for environment preparation to complete.".to_string());
        }

        Ok(python_exe.to_string_lossy().to_string())
    }

    /// Setup Python environment and install dependencies.
    /// Windows: embedded Python + offline wheels (no system Python needed)
    /// macOS/Linux: system Python + venv + pip install from network
    fn ensure_python_env(agent_dir: &Path, bridge_dir: &Path) -> Result<String, String> {
        #[cfg(windows)]
        {
            Self::ensure_python_env_windows(agent_dir, bridge_dir)
        }
        #[cfg(not(windows))]
        {
            Self::ensure_python_env_unix(agent_dir, bridge_dir)
        }
    }

    /// Windows: Setup embedded Python and install wheels offline.
    #[cfg(windows)]
    fn ensure_python_env_windows(agent_dir: &Path, bridge_dir: &Path) -> Result<String, String> {
        let python_dir = agent_dir.join("python");
        let python_exe = python_dir.join("python.exe");
        let marker = python_dir.join(".deps_installed");

        // Skip if already fully set up
        if python_exe.exists() && marker.exists() {
            return Ok(python_exe.to_string_lossy().to_string());
        }

        // Step 1: Copy embedded Python if not present
        if !python_exe.exists() {
            let embed_src = bridge_dir.join("python-embed");
            log::info!("Looking for embedded Python at: {}", embed_src.display());
            // .exe files are renamed to .bin in resources to avoid NSIS stripping them.
            // Check for python.bin (packaged) or python.exe (dev mode).
            let has_bin = embed_src.join("python.bin").exists();
            let has_exe = embed_src.join("python.exe").exists();
            if !has_bin && !has_exe {
                let dir_exists = embed_src.exists();
                let dir_contents: Vec<String> = if dir_exists {
                    std::fs::read_dir(&embed_src)
                        .map(|entries| entries.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string()).take(10).collect())
                        .unwrap_or_default()
                } else {
                    vec![]
                };
                return Err(format!(
                    "Embedded Python not found at: {}. dir_exists={}, files={:?}",
                    embed_src.display(), dir_exists, dir_contents
                ));
            }

            log::info!("Copying embedded Python to: {}", python_dir.display());
            Self::copy_dir_recursive(&embed_src, &python_dir)?;

            // Rename .bin back to .exe after copying (NSIS workaround)
            let bin_to_exe = [("python.bin", "python.exe"), ("pythonw.bin", "pythonw.exe")];
            for (bin_name, exe_name) in &bin_to_exe {
                let bin_path = python_dir.join(bin_name);
                let exe_path = python_dir.join(exe_name);
                if bin_path.exists() && !exe_path.exists() {
                    std::fs::rename(&bin_path, &exe_path)
                        .map_err(|e| format!("Failed to rename {} -> {}: {}", bin_name, exe_name, e))?;
                    log::info!("Renamed {} to {}", bin_name, exe_name);
                }
            }

            // Enable site-packages: uncomment "import site" in ._pth file
            let entries = std::fs::read_dir(&python_dir)
                .map_err(|e| format!("Failed to read python dir: {}", e))?;
            for entry in entries {
                if let Ok(entry) = entry {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if name.ends_with("._pth") {
                        let content = std::fs::read_to_string(entry.path())
                            .map_err(|e| format!("Failed to read {}: {}", name, e))?;
                        // Uncomment import site and add Lib/site-packages
                        let new_content = content.replace("#import site", "import site");
                        std::fs::write(entry.path(), new_content)
                            .map_err(|e| format!("Failed to write {}: {}", name, e))?;
                        log::info!("Enabled site-packages in {}", name);
                        break;
                    }
                }
            }

            // Create Lib/site-packages directory
            std::fs::create_dir_all(python_dir.join("Lib").join("site-packages"))
                .map_err(|e| format!("Failed to create site-packages: {}", e))?;
        }

        // Step 2: Install wheels offline using pip from wheel
        let wheels_dir = bridge_dir.join("wheels");
        if !wheels_dir.exists() {
            return Err(format!("Wheels directory not found at: {}", wheels_dir.display()));
        }

        // Find the pip wheel file
        let pip_wheel = Self::find_wheel_file(&wheels_dir, "pip")?;
        let req_file = bridge_dir.join("requirements.txt");

        log::info!("Installing Python packages from bundled wheels...");

        // Embedded Python ignores PYTHONPATH due to ._pth file.
        // Bootstrap pip by injecting the wheel path into sys.path via -c script.
        let bootstrap_script = format!(
            "import sys; sys.path.insert(0, r'{}'); from pip._internal.cli.main import main; sys.exit(main(['install', '--no-index', '--find-links', r'{}', '-r', r'{}', 'pip', 'setuptools']))",
            pip_wheel.to_string_lossy(),
            wheels_dir.to_string_lossy(),
            req_file.to_string_lossy(),
        );

        let mut pip_cmd = Command::new(python_exe.to_string_lossy().to_string());
        pip_cmd.args(["-c", &bootstrap_script])
            .env("PYTHONUTF8", "1");

        {
            use std::os::windows::process::CommandExt;
            pip_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let output = pip_cmd
            .output()
            .map_err(|e| format!("Failed to run pip install: {}", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let stdout = String::from_utf8_lossy(&output.stdout);
            // Clean up so next attempt starts fresh
            let _ = std::fs::remove_dir_all(&python_dir);
            return Err(format!("Failed to install Python packages: {} {}", stderr, stdout));
        }

        // Write marker
        let _ = std::fs::write(&marker, "ok");
        log::info!("Python environment ready (embedded + offline wheels)");

        Ok(python_exe.to_string_lossy().to_string())
    }

    /// macOS/Linux: Setup venv using system Python and install deps via pip.
    #[cfg(not(windows))]
    fn ensure_python_env_unix(agent_dir: &Path, bridge_dir: &Path) -> Result<String, String> {
        let venv_dir = agent_dir.join("venv");
        let python_exe = venv_dir.join("bin").join("python");
        let pip_exe = venv_dir.join("bin").join("pip");
        let marker = venv_dir.join(".deps_installed");

        // Skip if already fully set up
        if python_exe.exists() && marker.exists() {
            return Ok(python_exe.to_string_lossy().to_string());
        }

        // Step 1: Find system Python
        let system_python = Self::find_system_python()?;
        log::info!("Using system Python: {}", system_python);

        // Step 2: Create venv if not exists
        if !python_exe.exists() {
            log::info!("Creating virtual environment at: {}", venv_dir.display());
            let output = Command::new(&system_python)
                .args(["-m", "venv", &venv_dir.to_string_lossy()])
                .output()
                .map_err(|_| "创建 Python 虚拟环境失败，请确保已安装 Python 3.10+".to_string())?;

            if !output.status.success() {
                return Err("创建 Python 虚拟环境失败，请确保已安装 Python 3.10+\n\n安装命令：brew install python@3.12".to_string());
            }
        }

        // Step 3: Upgrade pip first (old pip may have SSL issues)
        log::info!("Upgrading pip...");
        let _ = Command::new(python_exe.to_string_lossy().to_string())
            .args(["-m", "pip", "install", "--upgrade", "pip"])
            .output();

        // Step 4: Install dependencies via pip
        let req_file = bridge_dir.join("requirements.txt");
        if !req_file.exists() {
            return Err("依赖配置文件丢失，请重新安装应用".to_string());
        }

        log::info!("Installing Python packages via pip...");
        let output = Command::new(pip_exe.to_string_lossy().to_string())
            .args(["install", "-r", &req_file.to_string_lossy()])
            .output()
            .map_err(|_| "安装 Python 依赖失败，请检查网络连接".to_string())?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            // Clean up so next attempt starts fresh
            let _ = std::fs::remove_dir_all(&venv_dir);

            // Provide user-friendly error messages
            if stderr.contains("SSL") || stderr.contains("connection") {
                return Err("安装依赖失败：网络连接异常\n\n请检查网络或配置代理后重试".to_string());
            } else if stderr.contains("No matching distribution") || stderr.contains("Could not find") {
                return Err("安装依赖失败：Python 版本过低\n\n请安装 Python 3.10+：brew install python@3.12".to_string());
            } else {
                return Err(format!("安装依赖失败：{}\n\n如问题持续，请尝试删除环境后重试",
                    stderr.lines().take(3).collect::<Vec<_>>().join("\n")));
            }
        }

        // Write marker
        let _ = std::fs::write(&marker, "ok");
        log::info!("Python environment ready (venv + pip)");

        Ok(python_exe.to_string_lossy().to_string())
    }

    /// Find system Python (python3 >= 3.10) on macOS/Linux
    #[cfg(not(windows))]
    fn find_system_python() -> Result<String, String> {
        // Try common Python paths - prioritize newer installations over system Python
        let candidates = [
            "/usr/local/bin/python3",      // Homebrew on Intel Mac
            "/opt/homebrew/bin/python3",   // Homebrew on Apple Silicon
            "/opt/local/bin/python3",      // MacPorts
            "/usr/bin/python3",            // System Python (often old)
        ];

        for path in &candidates {
            if let Some(python) = Self::check_python_version(path, 10) {
                return Ok(python);
            }
        }

        // Try `which python3`
        let output = Command::new("which")
            .arg("python3")
            .output();

        if let Ok(o) = output {
            if o.status.success() {
                let path = String::from_utf8_lossy(&o.stdout).trim().to_string();
                if let Some(python) = Self::check_python_version(&path, 10) {
                    return Ok(python);
                }
            }
        }

        Err("未找到 Python 3.10+\n\n请先安装 Python：\nmacOS: brew install python@3.12\nUbuntu: sudo apt install python3.12".to_string())
    }

    /// Check if Python at given path exists and meets minimum minor version requirement
    #[cfg(not(windows))]
    fn check_python_version(path: &str, min_minor: u32) -> Option<String> {
        if !std::path::Path::new(path).exists() {
            return None;
        }

        // Run python --version to check version
        let output = Command::new(path)
            .args(["--version"])
            .output()
            .ok()?;

        if !output.status.success() {
            return None;
        }

        // Parse "Python 3.X.Y"
        let version_str = String::from_utf8_lossy(&output.stdout);
        let version_str = version_str.trim();

        // Also check stderr (some Python versions print to stderr)
        let stderr_str = String::from_utf8_lossy(&output.stderr);
        let version_line = if version_str.starts_with("Python") {
            version_str
        } else if stderr_str.trim().starts_with("Python") {
            stderr_str.trim()
        } else {
            return None;
        };

        // Extract minor version from "Python 3.X.Y"
        let parts: Vec<&str> = version_line.split_whitespace().collect();
        if parts.len() < 2 {
            return None;
        }

        let version_parts: Vec<&str> = parts[1].split('.').collect();
        if version_parts.len() < 2 {
            return None;
        }

        let minor: u32 = version_parts[1].parse().ok()?;
        if minor >= min_minor {
            log::info!("Found Python {} at {}", parts[1], path);
            Some(path.to_string())
        } else {
            log::info!("Skipping {} (version {} < 3.{})", path, parts[1], min_minor);
            None
        }
    }

    /// Find a wheel file by package name prefix in the wheels directory
    fn find_wheel_file(wheels_dir: &Path, prefix: &str) -> Result<PathBuf, String> {
        let entries = std::fs::read_dir(wheels_dir)
            .map_err(|e| format!("Failed to read wheels dir: {}", e))?;

        let prefix_lower = format!("{}-", prefix.to_lowercase());
        for entry in entries {
            if let Ok(entry) = entry {
                let name = entry.file_name().to_string_lossy().to_lowercase();
                if name.starts_with(&prefix_lower) && name.ends_with(".whl") {
                    return Ok(entry.path());
                }
            }
        }

        Err(format!("Wheel file for '{}' not found in {}", prefix, wheels_dir.display()))
    }

    /// Initialize agent data directory with default configs
    fn init_agent_directory(agent_dir: &Path, bridge_dir: &Path) -> Result<(), String> {
        // Check if already initialized (presence of .env as marker)
        if agent_dir.join(".env").exists() {
            return Ok(());
        }

        log::info!("Initializing agent directory: {}", agent_dir.display());

        let defaults_dir = bridge_dir.join("defaults");

        // Create directory structure
        let dirs_to_create = [
            agent_dir.to_path_buf(),
            agent_dir.join("app"),
            agent_dir.join("workspace"),
            agent_dir.join("logs"),
            agent_dir.join(".claude"),
            agent_dir.join(".claude").join("skills"),
        ];

        for dir in &dirs_to_create {
            std::fs::create_dir_all(dir)
                .map_err(|e| format!("Failed to create dir {}: {}", dir.display(), e))?;
        }

        // Copy default config files
        let file_copies = [
            (".env.default", ".env"),
            (".mcp.json", ".mcp.json"),
            ("soul.md", "app/soul.md"),
            ("system_prompt.md", "app/system_prompt.md"),
            ("allowed_tools.txt", "allowed_tools.txt"),
            ("CLAUDE.md", "CLAUDE.md"),
        ];

        for (src_name, dst_name) in &file_copies {
            let src = defaults_dir.join(src_name);
            let dst = agent_dir.join(dst_name);
            if src.exists() && !dst.exists() {
                // Ensure parent dir exists
                if let Some(parent) = dst.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                std::fs::copy(&src, &dst)
                    .map_err(|e| format!("Failed to copy {} -> {}: {}", src.display(), dst.display(), e))?;
            }
        }

        // Copy .claude/skills/ directory recursively
        let skills_src = defaults_dir.join(".claude").join("skills");
        let skills_dst = agent_dir.join(".claude").join("skills");
        if skills_src.exists() {
            Self::copy_dir_recursive(&skills_src, &skills_dst)?;
        }

        log::info!("Agent directory initialized successfully");
        Ok(())
    }

    /// Recursively copy a directory
    fn copy_dir_recursive(src: &Path, dst: &Path) -> Result<(), String> {
        std::fs::create_dir_all(dst)
            .map_err(|e| format!("Failed to create dir {}: {}", dst.display(), e))?;

        let entries = std::fs::read_dir(src)
            .map_err(|e| format!("Failed to read dir {}: {}", src.display(), e))?;

        for entry in entries {
            let entry = entry.map_err(|e| format!("Dir entry error: {}", e))?;
            let src_path = entry.path();
            let dst_path = dst.join(entry.file_name());

            if src_path.is_dir() {
                Self::copy_dir_recursive(&src_path, &dst_path)?;
            } else if !dst_path.exists() {
                std::fs::copy(&src_path, &dst_path)
                    .map_err(|e| format!("Failed to copy {}: {}", src_path.display(), e))?;
            }
        }
        Ok(())
    }

    fn start_log_collection(project_id: &str) {
        let pid = project_id.to_string();

        let mut bridges = match BRIDGES.lock() {
            Ok(b) => b,
            Err(_) => return,
        };

        if let Some(group) = bridges.get_mut(&pid) {
            if let Some(stdout) = group.agent_server.stdout.take() {
                let pid_clone = pid.clone();
                std::thread::spawn(move || {
                    Self::collect_output(BufReader::new(stdout), &pid_clone, "[Agent]");
                });
            }
            if let Some(stderr) = group.agent_server.stderr.take() {
                let pid_clone = pid.clone();
                std::thread::spawn(move || {
                    Self::collect_output(BufReader::new(stderr), &pid_clone, "[Agent]");
                });
            }
            if let Some(stdout) = group.bridge_client.stdout.take() {
                let pid_clone = pid.clone();
                std::thread::spawn(move || {
                    Self::collect_output(BufReader::new(stdout), &pid_clone, "[Bridge]");
                });
            }
            if let Some(stderr) = group.bridge_client.stderr.take() {
                let pid_clone = pid.clone();
                std::thread::spawn(move || {
                    Self::collect_output(BufReader::new(stderr), &pid_clone, "[Bridge]");
                });
            }
        }
    }

    fn collect_output<R: IoRead>(reader: R, project_id: &str, prefix: &str) {
        // Use lossy UTF-8 decoding so non-UTF-8 output (e.g. GBK on Chinese Windows)
        // doesn't break the log collection loop.
        let buf_reader = BufReader::new(reader);
        let mut raw_line = Vec::new();
        let mut buf_reader = buf_reader;

        loop {
            raw_line.clear();
            match buf_reader.read_until(b'\n', &mut raw_line) {
                Ok(0) => break, // EOF
                Ok(_) => {
                    // Lossy decode: replaces invalid UTF-8 with U+FFFD
                    let text = String::from_utf8_lossy(&raw_line);
                    let text = text.trim_end_matches('\n').trim_end_matches('\r');
                    if text.is_empty() {
                        continue;
                    }
                    let log_line = format!("{} {}", prefix, text);
                    if let Ok(mut bridges) = BRIDGES.lock() {
                        if let Some(group) = bridges.get_mut(project_id) {
                            if group.logs.len() >= MAX_LOG_LINES {
                                group.logs.pop_front();
                            }
                            group.logs.push_back(log_line);
                        }
                    }
                }
                Err(_) => break,
            }
        }
    }
}
