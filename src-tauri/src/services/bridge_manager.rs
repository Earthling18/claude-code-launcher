use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::io::{BufRead, BufReader, Read as IoRead};
use tauri::Emitter;

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
static BRIDGE_CLIENT_LAST_FAIL: Lazy<Mutex<Option<std::time::Instant>>> = Lazy::new(|| Mutex::new(None));

pub struct BridgeManager;

impl BridgeManager {
    /// Get the mobot-bridge install directory: ~/.config/mobot-launcher/mobot-bridge/
    /// Migrates from old "claude-launcher" path if it exists.
    pub fn get_mobot_dir() -> PathBuf {
        let config_dir = dirs::config_dir().unwrap_or_else(|| PathBuf::from("."));
        let new_root = config_dir.join("mobot-launcher");
        let old_root = config_dir.join("claude-launcher");

        // Migrate: rename old directory to new if old exists and new doesn't
        if old_root.exists() && !new_root.exists() {
            log::info!(
                "Migrating data directory: {} -> {}",
                old_root.display(),
                new_root.display()
            );
            if let Err(e) = std::fs::rename(&old_root, &new_root) {
                log::error!("Migration failed (will use old path): {}", e);
                return old_root.join("mobot-bridge");
            }
            // Force re-install after migration so new files get copied over
            let mobot_dir = new_root.join("mobot-bridge");
            let _ = std::fs::remove_file(mobot_dir.join(".mobot_version"));
            let _ = std::fs::remove_file(mobot_dir.join(".deps_installed"));
            log::info!("Cleared markers after migration to force re-install");
        }

        new_root.join("mobot-bridge")
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

        // Stop any running bridge service first to release file locks (e.g. libcrypto-3.dll)
        log::info!("Stopping any running bridge service before install...");
        Self::stop_all();
        // Also kill any orphaned python processes using the bridge directory
        #[cfg(windows)]
        {
            let mobot_dir = Self::get_mobot_dir();
            let mobot_str = mobot_dir.to_string_lossy().to_string();
            if let Ok(output) = Command::new("wmic")
                .args(["process", "where", &format!("CommandLine like '%{}%'", mobot_str.replace('\\', "\\\\")), "get", "ProcessId"])
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .output()
            {
                let stdout = String::from_utf8_lossy(&output.stdout);
                for line in stdout.lines() {
                    if let Ok(pid) = line.trim().parse::<u32>() {
                        log::info!("Killing orphaned bridge process: PID={}", pid);
                        let _ = Command::new("taskkill")
                            .args(["/F", "/PID", &pid.to_string()])
                            .output();
                    }
                }
            }
        }
        // Brief pause to allow file handles to be released
        std::thread::sleep(std::time::Duration::from_millis(500));

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

        // Clean directories that must be replaced entirely (version-sensitive binaries)
        let python_embed_dir = mobot_dir.join("python-embed");
        if python_embed_dir.is_dir() {
            log::info!("Cleaning old python-embed/ for fresh install");
            let _ = std::fs::remove_dir_all(&python_embed_dir);
        }
        let lib_dir = mobot_dir.join("lib");
        if lib_dir.is_dir() {
            log::info!("Cleaning old lib/ for fresh wheel extraction");
            let _ = std::fs::remove_dir_all(&lib_dir);
        }

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
        let legacy_dirs = ["defaults"];
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

        // Clean __pycache__ directories to avoid .pyc magic number mismatch
        // (e.g. switching from a different system Python to embedded Python 3.12)
        // NOTE: only clean __pycache__ dirs, NOT loose .pyc files — app/ uses .pyc as source
        fn clean_pycache(dir: &Path) {
            if let Ok(entries) = std::fs::read_dir(dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        if path.file_name().map(|n| n == "__pycache__").unwrap_or(false) {
                            let _ = std::fs::remove_dir_all(&path);
                        } else {
                            clean_pycache(&path);
                        }
                    }
                }
            }
        }
        log::info!("Cleaning __pycache__ directories...");
        clean_pycache(&mobot_dir);

        // Write version marker from VERSION file, or fallback
        let version_marker = mobot_dir.join(".mobot_version");
        let version = std::fs::read_to_string(mobot_dir.join("VERSION"))
            .unwrap_or_else(|_| "1.0.0".to_string());
        let _ = std::fs::write(&version_marker, version.trim());

        log::info!("mobot-bridge installed successfully");
        Ok(mobot_dir.to_string_lossy().to_string())
    }

    /// Public wrapper for find_bridge_source (used by version check in commands)
    pub fn find_bridge_source_pub(resource_dir: &str) -> Result<PathBuf, String> {
        Self::find_bridge_source(resource_dir)
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

    /// Find the Tauri resource directory containing bridge source files.
    /// Used to repair files that may be overwritten by hot-update.
    fn find_resource_dir() -> Option<PathBuf> {
        // Try exe directory (installed) and dev mode
        if let Ok(exe) = std::env::current_exe() {
            if let Some(exe_dir) = exe.parent() {
                let candidates = [
                    exe_dir.join("resources").join("bridge"),
                    exe_dir.join("bridge"),
                    // Dev mode
                    Path::new(env!("CARGO_MANIFEST_DIR")).join("resources").join("bridge"),
                ];
                for candidate in &candidates {
                    if candidate.join("start.py").exists() {
                        return Some(candidate.clone());
                    }
                }
            }
        }
        None
    }

    /// Check if dependencies are installed (marker file exists)
    pub fn check_deps_installed(bridge_path: &str) -> bool {
        let marker = Path::new(bridge_path).join(".deps_installed");
        marker.exists()
    }

    /// Detect Python >= 3.10. Priority: embedded python > venv > system python.
    pub fn detect_python() -> Option<String> {
        let mobot_dir = Self::get_mobot_dir();

        // First check for bundled python-embed (fully offline, no system Python needed)
        #[cfg(windows)]
        {
            // python-embed stores python.exe as python.bin to avoid SmartScreen issues
            let embed_python = mobot_dir.join("python-embed").join("python.exe");
            let embed_python_bin = mobot_dir.join("python-embed").join("python.bin");
            if embed_python.exists() {
                log::info!("Using embedded Python: {}", embed_python.display());
                return Some(embed_python.to_string_lossy().to_string());
            }
            if embed_python_bin.exists() {
                // Try rename python.bin -> python.exe for use
                let exe_path = mobot_dir.join("python-embed").join("python.exe");
                match std::fs::rename(&embed_python_bin, &exe_path) {
                    Ok(_) => {
                        log::info!("Using embedded Python (renamed .bin -> .exe): {}", exe_path.display());
                        return Some(exe_path.to_string_lossy().to_string());
                    }
                    Err(e) => {
                        // Rename failed (permissions etc.), use python.bin directly
                        log::warn!("Failed to rename python.bin -> python.exe: {}, using python.bin directly", e);
                        return Some(embed_python_bin.to_string_lossy().to_string());
                    }
                }
            }
        }

        // Then check venv
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

        // Fall back to system Python
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

    /// Emit a progress event to the frontend (if app_handle is provided)
    fn emit_progress(app_handle: Option<&tauri::AppHandle>, msg: &str) {
        log::info!("[deps] {}", msg);
        if let Some(handle) = app_handle {
            let _ = handle.emit("mobot-deps-progress", msg);
        }
    }

    /// Install Python dependencies.
    /// Priority: offline wheels > online pip (via venv on macOS/Linux)
    /// Returns the python executable path to use for running the service
    pub fn install_dependencies(bridge_path: &str, python: &str, app_handle: Option<&tauri::AppHandle>) -> Result<String, String> {
        let bridge_dir = Path::new(bridge_path);
        let req_file = bridge_dir.join("requirements.txt");

        // Check if we have offline wheels available (Windows only — wheels contain .pyd binaries)
        #[cfg(windows)]
        {
            let wheels_dir = bridge_dir.join("wheels");
            let has_wheels = wheels_dir.exists()
                && std::fs::read_dir(&wheels_dir)
                    .map(|mut d| d.next().is_some())
                    .unwrap_or(false);

            if has_wheels {
                return Self::install_from_wheels(bridge_dir, python, &wheels_dir, app_handle);
            }
        }

        if !req_file.exists() {
            return Err(format!(
                "requirements.txt not found at {}",
                req_file.display()
            ));
        }

        Self::emit_progress(app_handle, "开始在线安装依赖...");

        #[cfg(not(windows))]
        let pip_python = {
            // macOS/Linux: create venv to avoid PEP 668 "externally-managed-environment" error
            let venv_dir = bridge_dir.join("venv");
            let venv_python = venv_dir.join("bin").join("python");
            let venv_pip = venv_dir.join("bin").join("pip");

            if !venv_python.exists() {
                Self::emit_progress(app_handle, "创建 Python 虚拟环境...");
                let output = Command::new(python)
                    .args(["-m", "venv", &venv_dir.to_string_lossy()])
                    .output()
                    .map_err(|e| format!("Failed to create venv: {}", e))?;

                if !output.status.success() {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    return Err(format!("Failed to create venv: {}", stderr));
                }
            }

            Self::emit_progress(app_handle, "升级 pip...");
            let _ = Command::new(venv_python.to_string_lossy().to_string())
                .args(["-m", "pip", "install", "--upgrade", "pip"])
                .output();

            Self::emit_progress(app_handle, "正在通过 pip 安装依赖包，可能需要几分钟...");
            let output = Command::new(venv_pip.to_string_lossy().to_string())
                .args(["install", "-r", &req_file.to_string_lossy()])
                .current_dir(bridge_dir)
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

            Self::emit_progress(app_handle, "pip 安装完成");
            venv_python.to_string_lossy().to_string()
        };

        #[cfg(windows)]
        let pip_python = {
            Self::emit_progress(app_handle, "正在通过 pip 安装依赖包，可能需要几分钟...");
            let mut cmd = Command::new(python);
            cmd.args(["-m", "pip", "install", "-r", &req_file.to_string_lossy()])
                .current_dir(bridge_dir);
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

            Self::emit_progress(app_handle, "pip 安装完成");
            python.to_string()
        };

        // Write install marker
        let marker = bridge_dir.join(".deps_installed");
        let _ = std::fs::write(&marker, "ok");

        Self::emit_progress(app_handle, "依赖安装完成 ✓");
        Ok(pip_python)
    }

    /// Install dependencies from offline wheels directory by extracting them to lib/
    #[cfg(windows)]
    fn install_from_wheels(bridge_dir: &Path, python: &str, wheels_dir: &Path, app_handle: Option<&tauri::AppHandle>) -> Result<String, String> {
        let lib_dir = bridge_dir.join("lib");

        // Skip if lib/ already has content (already extracted)
        if lib_dir.exists() {
            let has_content = std::fs::read_dir(&lib_dir)
                .map(|mut d| d.next().is_some())
                .unwrap_or(false);
            if has_content {
                Self::emit_progress(app_handle, "离线依赖已就绪，跳过解压");
                let marker = bridge_dir.join(".deps_installed");
                let _ = std::fs::write(&marker, "ok");
                return Ok(python.to_string());
            }
        }

        Self::emit_progress(app_handle, "正在解压离线依赖包...");

        // Create lib/ directory
        std::fs::create_dir_all(&lib_dir)
            .map_err(|e| format!("Failed to create lib/ directory: {}", e))?;

        // Count total wheels for progress
        let wheel_files: Vec<_> = std::fs::read_dir(wheels_dir)
            .into_iter()
            .flatten()
            .flatten()
            .filter(|e| e.path().extension().map(|ext| ext == "whl").unwrap_or(false))
            .collect();
        let total = wheel_files.len();

        // Extract each .whl file (wheels are just zip files)
        for (i, entry) in wheel_files.iter().enumerate() {
            let path = entry.path();
            let name = path.file_name().unwrap_or_default().to_string_lossy().to_string();
            // Extract package name from wheel filename (e.g. "pydantic-2.5.0-cp312-..." -> "pydantic")
            let pkg_name = name.split('-').next().unwrap_or(&name);
            Self::emit_progress(app_handle, &format!("解压依赖 ({}/{}) {}...", i + 1, total, pkg_name));

            let file = std::fs::File::open(&path)
                .map_err(|e| format!("Failed to open {}: {}", path.display(), e))?;
            let mut archive = zip::ZipArchive::new(file)
                .map_err(|e| format!("Failed to read wheel {}: {}", path.display(), e))?;
            archive.extract(&lib_dir)
                .map_err(|e| format!("Failed to extract {}: {}", path.display(), e))?;
        }

        // Write install marker
        let marker = bridge_dir.join(".deps_installed");
        let _ = std::fs::write(&marker, "ok");

        Self::emit_progress(app_handle, &format!("离线依赖解压完成，共 {} 个包 ✓", total));
        Ok(python.to_string())
    }

    /// Start mobot-bridge service
    pub fn start_service(bridge_path: &str, python: &str, port: u16) -> Result<u32, String> {
        let bridge_dir = Path::new(bridge_path);
        let start_py = bridge_dir.join("start.py");

        if !start_py.exists() {
            return Err(format!("start.py not found at {}", start_py.display()));
        }

        // Repair font files if missing
        Self::repair_fonts_if_needed();

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

        // Set PYTHONPATH: project root (for app/ imports) + lib/ (for wheel packages)
        // Embedded python with ._pth doesn't auto-add cwd to sys.path
        let lib_dir = bridge_dir.join("lib");
        let mut pythonpath = bridge_dir.to_string_lossy().to_string();
        if lib_dir.exists() {
            let sep = if cfg!(windows) { ";" } else { ":" };
            pythonpath = format!("{}{}{}", pythonpath, sep, lib_dir.to_string_lossy());
        }
        cmd.env("PYTHONPATH", &pythonpath);

        // pywin32 needs its DLLs (pywintypes311.dll) on PATH
        let pywin32_sys32 = lib_dir.join("pywin32_system32");
        if pywin32_sys32.exists() {
            let current_path = std::env::var("PATH").unwrap_or_default();
            let sep = if cfg!(windows) { ";" } else { ":" };
            cmd.env("PATH", format!("{}{}{}", pywin32_sys32.to_string_lossy(), sep, current_path));
        }

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
    /// Repair font files if missing (hot-update overwrites app/static/ without bundled fonts)
    /// Called from start_service() and periodically from check_health()
    fn repair_fonts_if_needed() {
        let mobot_dir = Self::get_mobot_dir();
        let font_file = mobot_dir.join("app").join("static").join("config").join("material-symbols-rounded.woff2");
        let font_css = mobot_dir.join("app").join("static").join("config").join("material-symbols.css");
        if font_file.exists() && font_css.exists() {
            return;
        }
        if let Some(res_dir) = Self::find_resource_dir() {
            let src_font = res_dir.join("app").join("static").join("config").join("material-symbols-rounded.woff2");
            let src_css = res_dir.join("app").join("static").join("config").join("material-symbols.css");
            if src_font.exists() && !font_file.exists() {
                let _ = std::fs::copy(&src_font, &font_file);
                log::info!("Repaired missing font file: {}", font_file.display());
            }
            if src_css.exists() && !font_css.exists() {
                let _ = std::fs::copy(&src_css, &font_css);
                log::info!("Repaired missing font CSS: {}", font_css.display());
            }
        }
    }

    pub fn check_health(port: u16) -> HealthStatus {
        let url = format!("http://127.0.0.1:{}/health", port);

        match reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(3))
            .no_proxy()
            .build()
        {
            Ok(client) => match client.get(&url).send() {
                Ok(resp) if resp.status().is_success() => {
                    // Check font files periodically (hot-update may remove them without restarting)
                    Self::repair_fonts_if_needed();
                    HealthStatus {
                        healthy: true,
                        details: resp.text().unwrap_or_default(),
                    }
                }
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

        let mut proc_lock = match MOBOT_PROCESS.lock() {
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

        if let Some(ref mut process) = *proc_lock {
            // Check if the process is actually still alive
            let still_alive = match process.child.try_wait() {
                Ok(None) => true,      // still running
                Ok(Some(_)) => false,  // exited
                Err(_) => false,       // error checking = assume dead
            };

            if still_alive {
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
                    installed: true,
                    running: false,
                    pid: None,
                    port: process.port,
                    install_path: Some(process.install_path.clone()),
                    healthy: false,
                    started_at: None,
                }
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

                // Set PYTHONPATH: project root + lib/ for embedded python
                let project_root = bridge_dir.parent().unwrap_or(&bridge_dir);
                let lib_dir = project_root.join("lib");
                let mut pythonpath = project_root.to_string_lossy().to_string();
                if lib_dir.exists() {
                    let sep = if cfg!(windows) { ";" } else { ":" };
            pythonpath = format!("{}{}{}", pythonpath, sep, lib_dir.to_string_lossy());
                }
                cmd.env("PYTHONPATH", &pythonpath);

                // pywin32 DLLs
                let pywin32_sys32 = lib_dir.join("pywin32_system32");
                if pywin32_sys32.exists() {
                    let current_path = std::env::var("PATH").unwrap_or_default();
                    let sep = if cfg!(windows) { ";" } else { ":" };
                    cmd.env("PATH", format!("{}{}{}", pywin32_sys32.to_string_lossy(), sep, current_path));
                }

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
                        // Clear failure cooldown on successful start
                        if let Ok(mut last_fail) = BRIDGE_CLIENT_LAST_FAIL.lock() {
                            *last_fail = None;
                        }
                    }
                    Err(e) => {
                        log::error!("Failed to start bridge client: {}", e);
                        // Record failure to prevent rapid retry
                        if let Ok(mut last_fail) = BRIDGE_CLIENT_LAST_FAIL.lock() {
                            *last_fail = Some(std::time::Instant::now());
                        }
                    }
                }

                // Clear starting flag
                if let Ok(mut starting) = BRIDGE_CLIENT_STARTING.lock() {
                    *starting = false;
                }
            }
        });
    }

    /// Ensure bridge client is running; restart if dead (with 60s cooldown to avoid spam)
    fn ensure_bridge_client(bridge_path: &str, python: &str) {
        // Prevent concurrent starts
        if let Ok(starting) = BRIDGE_CLIENT_STARTING.lock() {
            if *starting {
                return;
            }
        }

        // Cooldown: don't retry within 60s of last failure
        if let Ok(last_fail) = BRIDGE_CLIENT_LAST_FAIL.lock() {
            if let Some(t) = *last_fail {
                if t.elapsed() < std::time::Duration::from_secs(60) {
                    return;
                }
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
                    // Record failure time
                    if let Ok(mut last_fail) = BRIDGE_CLIENT_LAST_FAIL.lock() {
                        *last_fail = Some(std::time::Instant::now());
                    }
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
                // Try to overwrite; if file is locked (os error 32), skip if same size
                if let Err(e) = std::fs::copy(&src_path, &dst_path) {
                    let src_size = std::fs::metadata(&src_path).map(|m| m.len()).unwrap_or(0);
                    let dst_size = std::fs::metadata(&dst_path).map(|m| m.len()).unwrap_or(u64::MAX);
                    if dst_path.exists() && src_size == dst_size {
                        log::warn!("Skipping locked file (same size): {}", dst_path.display());
                    } else {
                        return Err(format!("Failed to copy {}: {}", src_path.display(), e));
                    }
                }
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
