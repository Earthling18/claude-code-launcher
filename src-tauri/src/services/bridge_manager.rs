use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::io::{BufRead, BufReader, Read as IoRead};

use once_cell::sync::Lazy;

/// Installation status of mobot-bridge
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum InstallStatus {
    NotInstalled,
    Installed { path: String },
    Running { path: String, port: u16 },
}

/// Health status from mobot-bridge /health endpoint
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthStatus {
    pub healthy: bool,
    pub details: String,
}

/// Service status returned to frontend
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MobotServiceStatus {
    pub installed: bool,
    pub running: bool,
    pub pid: Option<u32>,
    pub port: u16,
    pub install_path: Option<String>,
    pub healthy: bool,
    pub started_at: Option<u64>,
}

/// Internal process tracking
struct MobotProcess {
    child: Child,
    port: u16,
    started_at: u64,
    install_path: String,
    python_path: String,
    logs: std::collections::VecDeque<String>,
}

const MAX_LOG_LINES: usize = 500;

static MOBOT_PROCESS: Lazy<Mutex<Option<MobotProcess>>> = Lazy::new(|| Mutex::new(None));
static BRIDGE_CLIENT_PROCESS: Lazy<Mutex<Option<Child>>> = Lazy::new(|| Mutex::new(None));
static BRIDGE_CLIENT_STARTING: Lazy<Mutex<bool>> = Lazy::new(|| Mutex::new(false));

pub struct BridgeManager;

impl BridgeManager {
    /// Get the mobot-bridge install directory: ~/.config/claude-launcher/mobot-bridge/
    pub fn get_mobot_dir() -> PathBuf {
        dirs::config_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("claude-launcher")
            .join("mobot-bridge")
    }

    /// Detect mobot-bridge installation status.
    /// Requires both start.py and .mobot_version marker to consider it installed.
    /// The marker is written during install to distinguish from old bridge code.
    pub fn detect_installation() -> InstallStatus {
        let mobot_dir = Self::get_mobot_dir();
        let start_py = mobot_dir.join("start.py");
        let version_marker = mobot_dir.join(".mobot_version");

        // Must have start.py + version marker + deps installed
        let deps_marker = mobot_dir.join(".deps_installed");
        if !start_py.exists() || !version_marker.exists() || !deps_marker.exists() {
            return InstallStatus::NotInstalled;
        }

        let path = mobot_dir.to_string_lossy().to_string();

        // Check if process is tracked as running
        if let Ok(proc) = MOBOT_PROCESS.lock() {
            if proc.is_some() {
                let port = proc.as_ref().unwrap().port;
                return InstallStatus::Running { path, port };
            }
        }

        InstallStatus::Installed { path }
    }

    /// Install mobot-bridge: copy from resources to user directory
    pub fn install_mobot_bridge(resource_dir: &str) -> Result<String, String> {
        let resource_dir = resource_dir.strip_prefix(r"\\?\").unwrap_or(resource_dir);

        // Find bridge source in resources
        let bridge_src = Self::find_bridge_source(resource_dir)?;
        let mobot_dir = Self::get_mobot_dir();

        log::info!(
            "Installing mobot-bridge from {} to {}",
            bridge_src.display(),
            mobot_dir.display()
        );

        // Create target directory
        std::fs::create_dir_all(&mobot_dir)
            .map_err(|e| format!("Failed to create mobot-bridge directory: {}", e))?;

        // Copy all files from source to target
        Self::copy_dir_recursive(&bridge_src, &mobot_dir)?;

        // Restore renamed dot-files (Tauri doesn't bundle dotfiles)
        let env_example = mobot_dir.join("env.example");
        if env_example.exists() {
            let _ = std::fs::rename(&env_example, mobot_dir.join(".env.example"));
        }
        let mcp_example = mobot_dir.join("mcp.json.example");
        if mcp_example.exists() {
            let _ = std::fs::rename(&mcp_example, mobot_dir.join(".mcp.json.example"));
        }

        // Clean up legacy files that no longer exist in new version
        let legacy_dirs = ["defaults", "python-embed", "wheels"];
        for dir_name in &legacy_dirs {
            let legacy_dir = mobot_dir.join(dir_name);
            if legacy_dir.is_dir() {
                log::info!("Removing legacy directory: {}", legacy_dir.display());
                let _ = std::fs::remove_dir_all(&legacy_dir);
            }
        }

        // Force re-install dependencies (requirements may have changed)
        let deps_marker = mobot_dir.join(".deps_installed");
        if deps_marker.exists() {
            let _ = std::fs::remove_file(&deps_marker);
            log::info!("Cleared .deps_installed marker to force dependency re-install");
        }

        // Write version marker from VERSION file, or fallback
        let version_marker = mobot_dir.join(".mobot_version");
        let version = std::fs::read_to_string(mobot_dir.join("VERSION"))
            .unwrap_or_else(|_| "1.0.0".to_string());
        let _ = std::fs::write(&version_marker, version.trim());

        log::info!("mobot-bridge installed successfully");
        Ok(mobot_dir.to_string_lossy().to_string())
    }

    /// Find the bridge source directory in resources
    fn find_bridge_source(resource_dir: &str) -> Result<PathBuf, String> {
        // Try: resources/bridge/ under Tauri resource dir
        let candidates = [
            Path::new(resource_dir).join("resources").join("bridge"),
            Path::new(resource_dir).join("bridge"),
            // Dev mode fallback
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("resources")
                .join("bridge"),
        ];

        for candidate in &candidates {
            if candidate.join("start.py").exists() {
                return Ok(candidate.clone());
            }
        }

        Err(format!(
            "mobot-bridge source not found in resources. Checked: {:?}",
            candidates.iter().map(|p| p.display().to_string()).collect::<Vec<_>>()
        ))
    }

    /// Check if dependencies are installed (marker file exists)
    pub fn check_deps_installed(bridge_path: &str) -> bool {
        let marker = Path::new(bridge_path).join(".deps_installed");
        marker.exists()
    }

    /// Detect Python >= 3.10. Prefers venv python in mobot-bridge dir if available.
    pub fn detect_python() -> Option<String> {
        // First check if mobot-bridge has a venv with python already
        let mobot_dir = Self::get_mobot_dir();
        #[cfg(not(windows))]
        {
            let venv_python = mobot_dir.join("venv").join("bin").join("python");
            if venv_python.exists() {
                if let Some(p) = Self::check_python_path(&venv_python.to_string_lossy(), 10) {
                    return Some(p);
                }
            }
        }
        #[cfg(windows)]
        {
            let venv_python = mobot_dir.join("venv").join("Scripts").join("python.exe");
            if venv_python.exists() {
                if let Some(p) = Self::check_python_cmd(&venv_python.to_string_lossy(), 10) {
                    return Some(p);
                }
            }
        }

        #[cfg(windows)]
        {
            let candidates = ["py", "python3", "python"];
            for cmd in &candidates {
                if let Some(path) = Self::check_python_cmd(cmd, 10) {
                    return Some(path);
                }
            }
            None
        }
        #[cfg(not(windows))]
        {
            let candidates = [
                "/opt/homebrew/bin/python3.13",
                "/opt/homebrew/bin/python3.12",
                "/opt/homebrew/bin/python3.11",
                "/opt/homebrew/bin/python3.10",
                "/opt/homebrew/bin/python3",
                "/usr/local/bin/python3.13",
                "/usr/local/bin/python3.12",
                "/usr/local/bin/python3.11",
                "/usr/local/bin/python3.10",
                "/usr/local/bin/python3",
                "/opt/local/bin/python3",
                "/usr/bin/python3",
            ];

            for path in &candidates {
                if let Some(python) = Self::check_python_path(path, 10) {
                    return Some(python);
                }
            }

            // Try `which python3`
            if let Ok(output) = Command::new("which").arg("python3").output() {
                if output.status.success() {
                    let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
                    if let Some(python) = Self::check_python_path(&path, 10) {
                        return Some(python);
                    }
                }
            }

            None
        }
    }

    /// Install Python dependencies using pip (via venv on macOS/Linux)
    /// Returns the python executable path to use for running the service
    pub fn install_dependencies(bridge_path: &str, python: &str) -> Result<String, String> {
        let bridge_dir = Path::new(bridge_path);
        let req_file = bridge_dir.join("requirements.txt");

        if !req_file.exists() {
            return Err(format!(
                "requirements.txt not found at {}",
                req_file.display()
            ));
        }

        log::info!("Installing mobot-bridge dependencies...");

        #[cfg(not(windows))]
        let pip_python = {
            // macOS/Linux: create venv to avoid PEP 668 "externally-managed-environment" error
            let venv_dir = bridge_dir.join("venv");
            let venv_python = venv_dir.join("bin").join("python");
            let venv_pip = venv_dir.join("bin").join("pip");

            if !venv_python.exists() {
                log::info!("Creating venv at {}", venv_dir.display());
                let output = Command::new(python)
                    .args(["-m", "venv", &venv_dir.to_string_lossy()])
                    .env("HTTP_PROXY", "")
                    .env("HTTPS_PROXY", "")
                    .env("http_proxy", "")
                    .env("https_proxy", "")
                    .output()
                    .map_err(|e| format!("Failed to create venv: {}", e))?;

                if !output.status.success() {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    return Err(format!("Failed to create venv: {}", stderr));
                }
            }

            // Upgrade pip first (clear proxy/SSL to avoid interference)
            let _ = Command::new(venv_python.to_string_lossy().to_string())
                .args(["-m", "pip", "install", "--upgrade", "pip"])
                .env("HTTP_PROXY", "")
                .env("HTTPS_PROXY", "")
                .env("http_proxy", "")
                .env("https_proxy", "")
                .env("SSL_CERT_FILE", "")
                .env("REQUESTS_CA_BUNDLE", "")
                .env("CURL_CA_BUNDLE", "")
                .output();

            // Install deps using venv pip
            let output = Command::new(venv_pip.to_string_lossy().to_string())
                .args(["install", "-r", &req_file.to_string_lossy()])
                .current_dir(bridge_dir)
                .env("HTTP_PROXY", "")
                .env("HTTPS_PROXY", "")
                .env("http_proxy", "")
                .env("https_proxy", "")
                .env("SSL_CERT_FILE", "")
                .env("REQUESTS_CA_BUNDLE", "")
                .env("CURL_CA_BUNDLE", "")
                .output()
                .map_err(|e| format!("Failed to run pip install: {}", e))?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                let stdout = String::from_utf8_lossy(&output.stdout);
                return Err(format!(
                    "pip install failed:\n{}\n{}",
                    stderr.lines().take(10).collect::<Vec<_>>().join("\n"),
                    stdout.lines().take(5).collect::<Vec<_>>().join("\n")
                ));
            }

            venv_python.to_string_lossy().to_string()
        };

        #[cfg(windows)]
        let pip_python = {
            let mut cmd = Command::new(python);
            cmd.args(["-m", "pip", "install", "-r", &req_file.to_string_lossy()])
                .current_dir(bridge_dir);
            cmd.env("HTTP_PROXY", "");
            cmd.env("HTTPS_PROXY", "");
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x08000000);
            }

            let output = cmd
                .output()
                .map_err(|e| format!("Failed to run pip install: {}", e))?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                let stdout = String::from_utf8_lossy(&output.stdout);
                return Err(format!(
                    "pip install failed:\n{}\n{}",
                    stderr.lines().take(10).collect::<Vec<_>>().join("\n"),
                    stdout.lines().take(5).collect::<Vec<_>>().join("\n")
                ));
            }

            python.to_string()
        };

        // Write install marker
        let marker = bridge_dir.join(".deps_installed");
        let _ = std::fs::write(&marker, "ok");

        log::info!("mobot-bridge dependencies installed successfully");
        Ok(pip_python)
    }

    /// Start mobot-bridge service
    pub fn start_service(bridge_path: &str, python: &str, port: u16) -> Result<u32, String> {
        let bridge_dir = Path::new(bridge_path);
        let start_py = bridge_dir.join("start.py");

        if !start_py.exists() {
            return Err(format!("start.py not found at {}", start_py.display()));
        }

        // Stop existing service if running
        let _ = Self::stop_service();

        // Kill any leftover process on the port
        Self::kill_process_on_port(port);

        log::info!("Starting mobot-bridge on port {}...", port);

        let mut cmd = Command::new(python);
        cmd.arg("-u")
            .arg(start_py.to_string_lossy().to_string())
            .current_dir(bridge_dir)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .env("WECOM_PORT", port.to_string())
            .env("WECOM_HOST", "127.0.0.1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Note: Do NOT clear proxy vars for Agent service — it needs proxy
        // to reach Anthropic API. Agent reads proxy from .env and manages it.

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000);
        }

        let child = cmd
            .spawn()
            .map_err(|e| format!("Failed to start mobot-bridge: {}", e))?;

        let pid = child.id();
        log::info!("mobot-bridge started, pid={}", pid);

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        let process = MobotProcess {
            child,
            port,
            started_at: now,
            install_path: bridge_path.to_string(),
            python_path: python.to_string(),
            logs: std::collections::VecDeque::with_capacity(MAX_LOG_LINES),
        };

        let mut proc_lock = MOBOT_PROCESS
            .lock()
            .map_err(|e| format!("Lock error: {}", e))?;
        *proc_lock = Some(process);
        drop(proc_lock);

        // Start log collection
        Self::start_log_collection();

        // Start bridge client (bridge_clientv3.py) as a separate process
        Self::start_bridge_client(bridge_path, python);

        Ok(pid)
    }

    /// Stop mobot-bridge service (both Agent and Bridge Client)
    pub fn stop_service() -> Result<(), String> {
        // Stop bridge client first
        Self::stop_bridge_client();

        let mut proc_lock = MOBOT_PROCESS
            .lock()
            .map_err(|e| format!("Lock error: {}", e))?;

        if let Some(mut process) = proc_lock.take() {
            // Try graceful shutdown via API first
            let port = process.port;
            drop(proc_lock); // Release lock during HTTP call

            let shutdown_ok = Self::try_graceful_shutdown(port);

            if !shutdown_ok {
                // Force kill
                let mut proc_lock = MOBOT_PROCESS
                    .lock()
                    .map_err(|e| format!("Lock error: {}", e))?;
                // Process might have been taken by another thread
                if proc_lock.is_none() {
                    // Re-insert to kill it
                    Self::kill_child(&mut process.child);
                } else if let Some(ref mut p) = *proc_lock {
                    Self::kill_child(&mut p.child);
                    *proc_lock = None;
                }
            } else {
                // Give the process a moment to shut down
                std::thread::sleep(std::time::Duration::from_millis(500));
                // Ensure it's dead
                let mut proc_lock = MOBOT_PROCESS
                    .lock()
                    .map_err(|e| format!("Lock error: {}", e))?;
                if let Some(ref mut p) = *proc_lock {
                    Self::kill_child(&mut p.child);
                }
                *proc_lock = None;
            }

            log::info!("mobot-bridge stopped");
        }

        Ok(())
    }

    /// Check mobot-bridge health via GET /health
    pub fn check_health(port: u16) -> HealthStatus {
        let url = format!("http://127.0.0.1:{}/health", port);

        match reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(3))
            .no_proxy()
            .build()
        {
            Ok(client) => match client.get(&url).send() {
                Ok(resp) if resp.status().is_success() => HealthStatus {
                    healthy: true,
                    details: resp.text().unwrap_or_default(),
                },
                Ok(resp) => HealthStatus {
                    healthy: false,
                    details: format!("HTTP {}", resp.status()),
                },
                Err(e) => HealthStatus {
                    healthy: false,
                    details: format!("Connection failed: {}", e),
                },
            },
            Err(e) => HealthStatus {
                healthy: false,
                details: format!("Client error: {}", e),
            },
        }
    }

    /// Get comprehensive service status
    pub fn get_service_status(port: u16) -> MobotServiceStatus {
        let mobot_dir = Self::get_mobot_dir();
        let installed = mobot_dir.join("start.py").exists();

        let proc_lock = match MOBOT_PROCESS.lock() {
            Ok(p) => p,
            Err(_) => {
                return MobotServiceStatus {
                    installed,
                    running: false,
                    pid: None,
                    port,
                    install_path: if installed {
                        Some(mobot_dir.to_string_lossy().to_string())
                    } else {
                        None
                    },
                    healthy: false,
                    started_at: None,
                }
            }
        };

        if let Some(ref process) = *proc_lock {
            let health = Self::check_health(process.port);

            // Auto-restart bridge client if service is healthy but client died
            if health.healthy {
                Self::ensure_bridge_client(&process.install_path, &process.python_path);
            }

            MobotServiceStatus {
                installed: true,
                running: true,
                pid: Some(process.child.id()),
                port: process.port,
                install_path: Some(process.install_path.clone()),
                healthy: health.healthy,
                started_at: Some(process.started_at),
            }
        } else {
            MobotServiceStatus {
                installed,
                running: false,
                pid: None,
                port,
                install_path: if installed {
                    Some(mobot_dir.to_string_lossy().to_string())
                } else {
                    None
                },
                healthy: false,
                started_at: None,
            }
        }
    }

    /// Get collected logs
    pub fn get_logs(max_lines: usize) -> Vec<String> {
        let proc_lock = match MOBOT_PROCESS.lock() {
            Ok(p) => p,
            Err(_) => return vec![],
        };

        if let Some(ref process) = *proc_lock {
            let count = max_lines.min(process.logs.len());
            process.logs.iter().rev().take(count).rev().cloned().collect()
        } else {
            vec![]
        }
    }

    /// Stop all processes (called on app exit)
    pub fn stop_all() {
        // Stop bridge client
        Self::stop_bridge_client();

        let mut proc_lock = match MOBOT_PROCESS.lock() {
            Ok(p) => p,
            Err(_) => return,
        };

        if let Some(ref mut process) = *proc_lock {
            log::info!("Stopping mobot-bridge on app exit");
            Self::kill_child(&mut process.child);
        }
        *proc_lock = None;
    }

    /// Get hostname (for display / connection command)
    pub fn get_hostname() -> String {
        if let Some(home) = dirs::home_dir() {
            let id_file = home.join(".agent-bridge").join("client_id");
            if let Ok(id) = std::fs::read_to_string(&id_file) {
                let id = id.trim().to_string();
                if !id.is_empty() {
                    return id;
                }
            }
        }
        std::env::var("COMPUTERNAME")
            .or_else(|_| std::env::var("HOSTNAME"))
            .unwrap_or_else(|_| "unknown".to_string())
    }

    /// Get username
    pub fn get_username() -> String {
        std::env::var("USERNAME")
            .or_else(|_| std::env::var("USER"))
            .unwrap_or_else(|_| "unknown".to_string())
            .to_lowercase()
    }

    /// Check if mobot-bridge is currently updating (restart_helper.py or update.py running)
    pub fn is_updating() -> bool {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            // Check for update.py or restart_helper.py in process list
            if let Ok(output) = Command::new("cmd")
                .args(&["/c", "tasklist /FI \"IMAGENAME eq python*\" /FO CSV /NH"])
                .creation_flags(CREATE_NO_WINDOW)
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .output()
            {
                let stdout = String::from_utf8_lossy(&output.stdout).to_lowercase();
                // Also check via wmic for command line args
                if let Ok(wmic_out) = Command::new("cmd")
                    .args(&["/c", "wmic process where \"name like '%python%'\" get commandline /format:list"])
                    .creation_flags(CREATE_NO_WINDOW)
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null())
                    .output()
                {
                    let cmdlines = String::from_utf8_lossy(&wmic_out.stdout).to_lowercase();
                    if cmdlines.contains("update.py") || cmdlines.contains("restart_helper.py") {
                        return true;
                    }
                }
            }
            false
        }

        #[cfg(not(windows))]
        {
            if let Ok(output) = Command::new("sh")
                .args(&["-c", "ps aux | grep -E 'update\\.py|restart_helper\\.py' | grep -v grep"])
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .output()
            {
                let stdout = String::from_utf8_lossy(&output.stdout);
                return !stdout.trim().is_empty();
            }
            false
        }
    }

    // ==================== Private helpers ====================

    /// Start bridge_clientv3.py as a separate process
    fn start_bridge_client(bridge_path: &str, python: &str) {
        let bridge_dir = Path::new(bridge_path).join("bridge");
        let script = bridge_dir.join("bridge_clientv3.py");

        if !script.exists() {
            log::info!("Bridge client script not found at {}, skipping", script.display());
            return;
        }

        // Wait a bit for the Agent service to be ready
        std::thread::spawn({
            let python = python.to_string();
            let bridge_dir = bridge_dir.clone();
            let script = script.clone();
            move || {
                // Mark as starting to prevent concurrent launches
                if let Ok(mut starting) = BRIDGE_CLIENT_STARTING.lock() {
                    *starting = true;
                }

                // Wait for Agent to start listening before launching bridge client
                std::thread::sleep(std::time::Duration::from_secs(5));

                log::info!("Starting bridge client: {}", script.display());

                // Redirect stderr to a log file so we can diagnose crashes
                let stderr_log = bridge_dir.join("bridge_client_stderr.log");
                let stderr_file = std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&stderr_log);

                let mut cmd = Command::new(&python);
                cmd.arg("-u")
                    .arg(script.to_string_lossy().to_string())
                    .current_dir(&bridge_dir)
                    .env("PYTHONUNBUFFERED", "1")
                    .env("PYTHONIOENCODING", "utf-8")
                    .env("PYTHONUTF8", "1")
                    .stdout(Stdio::null());

                match stderr_file {
                    Ok(f) => { cmd.stderr(Stdio::from(f)); }
                    Err(_) => { cmd.stderr(Stdio::null()); }
                }

                // Bridge must NOT use proxy
                cmd.env_remove("HTTP_PROXY");
                cmd.env_remove("HTTPS_PROXY");
                cmd.env_remove("ALL_PROXY");
                cmd.env_remove("http_proxy");
                cmd.env_remove("https_proxy");
                cmd.env_remove("all_proxy");

                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
                }

                match cmd.spawn() {
                    Ok(child) => {
                        log::info!("Bridge client started, pid={}", child.id());
                        if let Ok(mut lock) = BRIDGE_CLIENT_PROCESS.lock() {
                            *lock = Some(child);
                        }
                    }
                    Err(e) => {
                        log::error!("Failed to start bridge client: {}", e);
                    }
                }

                // Clear starting flag
                if let Ok(mut starting) = BRIDGE_CLIENT_STARTING.lock() {
                    *starting = false;
                }
            }
        });
    }

    /// Ensure bridge client is running; restart if dead
    fn ensure_bridge_client(bridge_path: &str, python: &str) {
        // Prevent concurrent starts
        if let Ok(starting) = BRIDGE_CLIENT_STARTING.lock() {
            if *starting {
                return;
            }
        }

        if let Ok(mut lock) = BRIDGE_CLIENT_PROCESS.lock() {
            let alive = match *lock {
                Some(ref mut child) => child.try_wait().ok().flatten().is_none(),
                None => false,
            };
            if !alive {
                if lock.is_some() {
                    log::info!("Bridge client process died, restarting...");
                    *lock = None;
                }
                drop(lock);
                Self::start_bridge_client(bridge_path, python);
            }
        }
    }

    /// Stop the bridge client process
    fn stop_bridge_client() {
        if let Ok(mut lock) = BRIDGE_CLIENT_PROCESS.lock() {
            if let Some(ref mut child) = *lock {
                log::info!("Stopping bridge client, pid={}", child.id());
                Self::kill_child(child);
            }
            *lock = None;
        }
    }

    fn try_graceful_shutdown(port: u16) -> bool {
        let url = format!("http://127.0.0.1:{}/api/config/shutdown", port);
        if let Ok(client) = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .no_proxy()
            .build()
        {
            if let Ok(resp) = client.post(&url).send() {
                return resp.status().is_success();
            }
        }
        false
    }

    fn kill_process_on_port(port: u16) {
        #[cfg(windows)]
        {
            let output = Command::new("cmd")
                .args([
                    "/C",
                    &format!(
                        "netstat -ano | findstr \"LISTENING\" | findstr \":{port} \""
                    ),
                ])
                .output();
            if let Ok(o) = output {
                let stdout = String::from_utf8_lossy(&o.stdout);
                for line in stdout.lines() {
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
                            let _ = Command::new("kill")
                                .args(["-9", &pid.to_string()])
                                .output();
                        }
                    }
                }
            }
        }
    }

    fn kill_child(child: &mut Child) {
        #[cfg(windows)]
        {
            let pid = child.id();
            let output = Command::new("taskkill")
                .args(["/F", "/T", "/PID", &pid.to_string()])
                .output();
            match output {
                Ok(o) if !o.status.success() => {
                    let _ = child.kill();
                }
                Err(_) => {
                    let _ = child.kill();
                }
                _ => {}
            }
        }
        #[cfg(not(windows))]
        {
            let _ = child.kill();
        }
        let _ = child.wait();
    }

    /// Check a python command (e.g. "python3") is available and meets version requirement
    #[cfg(windows)]
    fn check_python_cmd(cmd: &str, min_minor: u32) -> Option<String> {
        let output = Command::new(cmd).args(["--version"]).output().ok()?;
        if !output.status.success() {
            return None;
        }
        Self::parse_python_version(&output.stdout, &output.stderr, cmd, min_minor)
    }

    /// Check a python path exists and meets version requirement
    #[cfg(not(windows))]
    fn check_python_path(path: &str, min_minor: u32) -> Option<String> {
        if !Path::new(path).exists() {
            return None;
        }
        let output = Command::new(path).args(["--version"]).output().ok()?;
        if !output.status.success() {
            return None;
        }
        Self::parse_python_version(&output.stdout, &output.stderr, path, min_minor)
    }

    fn parse_python_version(
        stdout: &[u8],
        stderr: &[u8],
        path: &str,
        min_minor: u32,
    ) -> Option<String> {
        let stdout_str = String::from_utf8_lossy(stdout);
        let stderr_str = String::from_utf8_lossy(stderr);

        let version_line = if stdout_str.trim().starts_with("Python") {
            stdout_str.trim().to_string()
        } else if stderr_str.trim().starts_with("Python") {
            stderr_str.trim().to_string()
        } else {
            return None;
        };

        let parts: Vec<&str> = version_line.split_whitespace().collect();
        if parts.len() < 2 {
            return None;
        }

        let version_parts: Vec<&str> = parts[1].split('.').collect();
        if version_parts.len() < 2 {
            return None;
        }

        let major: u32 = version_parts[0].parse().ok()?;
        let minor: u32 = version_parts[1].parse().ok()?;

        if major == 3 && minor >= min_minor {
            log::info!("Found Python {} at {}", parts[1], path);
            Some(path.to_string())
        } else {
            log::info!("Skipping {} (version {} < 3.{})", path, parts[1], min_minor);
            None
        }
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
            } else {
                // Always overwrite during install (ensures updates are applied)
                std::fs::copy(&src_path, &dst_path).map_err(|e| {
                    format!("Failed to copy {}: {}", src_path.display(), e)
                })?;
            }
        }
        Ok(())
    }

    fn start_log_collection() {
        let mut proc_lock = match MOBOT_PROCESS.lock() {
            Ok(p) => p,
            Err(_) => return,
        };

        if let Some(ref mut process) = *proc_lock {
            if let Some(stdout) = process.child.stdout.take() {
                std::thread::spawn(move || {
                    Self::collect_output(BufReader::new(stdout), "[mobot]");
                });
            }
            if let Some(stderr) = process.child.stderr.take() {
                std::thread::spawn(move || {
                    Self::collect_output(BufReader::new(stderr), "[mobot]");
                });
            }
        }
    }

    fn collect_output<R: IoRead + Send + 'static>(reader: R, prefix: &str) {
        let prefix = prefix.to_string();
        let mut buf_reader = BufReader::new(reader);
        let mut raw_line = Vec::new();

        loop {
            raw_line.clear();
            match buf_reader.read_until(b'\n', &mut raw_line) {
                Ok(0) => break,
                Ok(_) => {
                    let text = String::from_utf8_lossy(&raw_line);
                    let text = text.trim_end_matches('\n').trim_end_matches('\r');
                    if text.is_empty() {
                        continue;
                    }
                    let log_line = format!("{} {}", prefix, text);
                    if let Ok(mut proc_lock) = MOBOT_PROCESS.lock() {
                        if let Some(ref mut process) = *proc_lock {
                            if process.logs.len() >= MAX_LOG_LINES {
                                process.logs.pop_front();
                            }
                            process.logs.push_back(log_line);
                        }
                    }
                }
                Err(_) => break,
            }
        }
    }
}
