use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::hash::{Hash, Hasher};
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use sysinfo::{Pid, ProcessesToUpdate, System};

const REPORT_SCHEMA: u32 = 1;
const DEDUPE_SECONDS: u64 = 24 * 60 * 60;
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CompatibilityStage {
    Standard,
    NoSandbox,
    NoSandboxDisableGpu,
}

impl CompatibilityStage {
    pub fn browser_args(self) -> String {
        match self {
            // An explicit empty value prevents Wry from injecting its default
            // feature flags. Those flags create a distinct WebView2 environment
            // and regress warm startup by several seconds on healthy machines.
            Self::Standard => String::new(),
            Self::NoSandbox => "--no-sandbox".to_string(),
            Self::NoSandboxDisableGpu => "--no-sandbox --disable-gpu".to_string(),
        }
    }

    fn next(self) -> Option<Self> {
        match self {
            Self::Standard => Some(Self::NoSandbox),
            Self::NoSandbox => Some(Self::NoSandboxDisableGpu),
            Self::NoSandboxDisableGpu => None,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Standard => "标准模式",
            Self::NoSandbox => "兼容模式（关闭 WebView 沙箱）",
            Self::NoSandboxDisableGpu => "兼容模式（关闭沙箱与 GPU）",
        }
    }
}

#[derive(Debug, Clone)]
pub struct BootstrapDiagnostics {
    pub stage: CompatibilityStage,
    pub preferred_fallback: Option<CompatibilityStage>,
    pub incident_id: String,
    pub browser_args: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RecoveryState {
    stage: CompatibilityStage,
    app_version: String,
    updated_at: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DiagnosticSettings {
    auto_report_enabled: bool,
    install_id: String,
    #[serde(default)]
    last_report_id: Option<String>,
    #[serde(default)]
    last_report_kind: Option<String>,
    #[serde(default)]
    last_report_at: Option<u64>,
}

impl Default for DiagnosticSettings {
    fn default() -> Self {
        Self {
            auto_report_enabled: true,
            install_id: new_id("install"),
            last_report_id: None,
            last_report_kind: None,
            last_report_at: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct DedupeState {
    fingerprints: HashMap<String, u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiagnosticsStatus {
    pub auto_report_enabled: bool,
    pub compatibility_stage: CompatibilityStage,
    pub compatibility_label: String,
    pub log_directory: String,
    pub endpoint_configured: bool,
    pub pending_reports: usize,
    pub last_report_id: Option<String>,
    pub last_report_kind: Option<String>,
    pub last_report_at: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ProcessSnapshot {
    browser_count: usize,
    renderer_count: usize,
    gpu_count: usize,
    utility_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DiagnosticReport {
    schema_version: u32,
    incident_id: String,
    install_id: String,
    kind: String,
    occurred_at: u64,
    app_version: String,
    os_version: String,
    compatibility_stage: CompatibilityStage,
    samples: Vec<ProcessSnapshot>,
    note: Option<String>,
    diagnostic_log_tail: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct SubmitResponse {
    accepted: bool,
    report_id: Option<String>,
}

pub fn diagnostics_dir() -> PathBuf {
    dirs::data_local_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("com.claudecode.launcher")
        .join("diagnostics")
}

fn ensure_dir() -> PathBuf {
    let path = diagnostics_dir();
    let _ = fs::create_dir_all(&path);
    path
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or(0)
}

fn new_id(prefix: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or(0);
    format!("{}-{:x}-{:x}", prefix, nanos, std::process::id())
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &PathBuf) -> Option<T> {
    fs::read_to_string(path)
        .ok()
        .and_then(|value| serde_json::from_str(&value).ok())
}

fn write_json<T: Serialize>(path: &PathBuf, value: &T) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temp = path.with_extension("tmp");
    let body = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    fs::write(&temp, body).map_err(|error| error.to_string())?;
    if path.exists() {
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    fs::rename(temp, path).map_err(|error| error.to_string())
}

fn recovery_path() -> PathBuf {
    ensure_dir().join("webview-recovery.json")
}
fn settings_path() -> PathBuf {
    ensure_dir().join("settings.json")
}
fn dedupe_path() -> PathBuf {
    ensure_dir().join("dedupe.json")
}
fn pending_dir() -> PathBuf {
    ensure_dir().join("pending")
}

fn load_settings() -> DiagnosticSettings {
    let path = settings_path();
    if let Some(settings) = read_json(&path) {
        settings
    } else {
        let settings = DiagnosticSettings::default();
        let _ = write_json(&path, &settings);
        settings
    }
}

fn explicit_stage() -> Option<CompatibilityStage> {
    for arg in std::env::args() {
        if let Some(value) = arg.strip_prefix("--webview-compat=") {
            return match value {
                "standard" => Some(CompatibilityStage::Standard),
                "no-sandbox" => Some(CompatibilityStage::NoSandbox),
                "software" => Some(CompatibilityStage::NoSandboxDisableGpu),
                _ => None,
            };
        }
        if let Some(value) = arg.strip_prefix("--webview-recovery-stage=") {
            return match value {
                "1" => Some(CompatibilityStage::NoSandbox),
                "2" => Some(CompatibilityStage::NoSandboxDisableGpu),
                _ => None,
            };
        }
    }
    None
}

fn incident_arg() -> Option<String> {
    std::env::args().find_map(|arg| arg.strip_prefix("--webview-incident=").map(str::to_string))
}

pub fn wait_for_recovery_parent() {
    let Some(parent) = std::env::args().find_map(|arg| {
        arg.strip_prefix("--webview-restart-parent=")
            .and_then(|value| value.parse::<u32>().ok())
    }) else {
        return;
    };
    let started = std::time::Instant::now();
    while started.elapsed() < Duration::from_secs(15) {
        let mut system = System::new();
        system.refresh_processes(ProcessesToUpdate::Some(&[Pid::from_u32(parent)]), true);
        if system.process(Pid::from_u32(parent)).is_none() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

pub fn prepare_boot(app_version: &str) -> BootstrapDiagnostics {
    if std::env::args().any(|arg| arg == "--reset-webview-compat") {
        let _ = fs::remove_file(recovery_path());
    }
    let stored: Option<RecoveryState> = read_json(&recovery_path());
    let explicit = explicit_stage();
    let (stage, preferred_fallback) = if let Some(stage) = explicit {
        (stage, None)
    } else if let Some(state) = stored {
        if state.app_version == app_version {
            (state.stage, None)
        } else {
            (CompatibilityStage::Standard, Some(state.stage))
        }
    } else {
        (CompatibilityStage::Standard, None)
    };
    BootstrapDiagnostics {
        stage,
        preferred_fallback,
        incident_id: incident_arg().unwrap_or_else(|| new_id("incident")),
        browser_args: stage.browser_args(),
    }
}

pub fn mark_page_loaded(stage: CompatibilityStage, app_version: &str) {
    let state = RecoveryState {
        stage,
        app_version: app_version.to_string(),
        updated_at: now_secs(),
    };
    if let Err(error) = write_json(&recovery_path(), &state) {
        log::warn!(target: "diagnostics", "failed to persist WebView recovery state: {}", error);
    } else {
        log::info!(target: "diagnostics", "WebView page loaded with stage={:?}", stage);
    }
    std::thread::spawn(retry_pending_reports);
}

fn snapshot_webview_processes(root_pid: u32) -> ProcessSnapshot {
    let mut system = System::new_all();
    system.refresh_processes(ProcessesToUpdate::All, true);
    let mut descendants = HashSet::from([Pid::from_u32(root_pid)]);
    loop {
        let before = descendants.len();
        for (pid, process) in system.processes() {
            if process
                .parent()
                .map(|value| descendants.contains(&value))
                .unwrap_or(false)
            {
                descendants.insert(*pid);
            }
        }
        if descendants.len() == before {
            break;
        }
    }
    let mut result = ProcessSnapshot {
        browser_count: 0,
        renderer_count: 0,
        gpu_count: 0,
        utility_count: 0,
    };
    for pid in descendants {
        let Some(process) = system.process(pid) else {
            continue;
        };
        if !process
            .name()
            .to_string_lossy()
            .eq_ignore_ascii_case("msedgewebview2.exe")
        {
            continue;
        }
        let command = process
            .cmd()
            .iter()
            .map(|value| value.to_string_lossy())
            .collect::<Vec<_>>()
            .join(" ");
        if command.contains("--type=renderer") {
            result.renderer_count += 1;
        } else if command.contains("--type=gpu-process") {
            result.gpu_count += 1;
        } else if command.contains("--type=utility") {
            result.utility_count += 1;
        } else {
            result.browser_count += 1;
        }
    }
    result
}

fn renderer_missing_confirmed(samples: &[ProcessSnapshot]) -> bool {
    samples.len() == 3
        && samples
            .iter()
            .all(|sample| sample.browser_count > 0 && sample.renderer_count == 0)
}

pub fn start_white_screen_monitor(
    app: tauri::AppHandle,
    loaded: Arc<AtomicBool>,
    boot: BootstrapDiagnostics,
    app_version: String,
) {
    #[cfg(not(windows))]
    {
        let _ = (app, loaded, boot, app_version);
    }

    #[cfg(windows)]
    std::thread::spawn(move || {
        let root_pid = std::process::id();
        let mut samples = Vec::new();
        for delay in [8_u64, 4, 4] {
            std::thread::sleep(Duration::from_secs(delay));
            if loaded.load(Ordering::Acquire) {
                return;
            }
            let sample = snapshot_webview_processes(root_pid);
            log::warn!(target: "diagnostics", "WebView sample browser={} renderer={} gpu={} utility={}", sample.browser_count, sample.renderer_count, sample.gpu_count, sample.utility_count);
            samples.push(sample);
        }
        if loaded.load(Ordering::Acquire) {
            return;
        }
        if !renderer_missing_confirmed(&samples) {
            return;
        }

        let report = build_report(
            "webview_renderer_missing",
            &boot.incident_id,
            &app_version,
            boot.stage,
            samples,
            None,
        );
        submit_or_queue(report, true);

        let next = boot
            .preferred_fallback
            .filter(|stage| *stage > boot.stage)
            .or_else(|| boot.stage.next());
        if let Some(next) = next {
            if let Ok(exe) = std::env::current_exe() {
                let stage_number = if next == CompatibilityStage::NoSandbox {
                    "1"
                } else {
                    "2"
                };
                let spawned = std::process::Command::new(exe)
                    .arg(format!("--webview-recovery-stage={}", stage_number))
                    .arg(format!("--webview-incident={}", boot.incident_id))
                    .arg(format!("--webview-restart-parent={}", root_pid))
                    .spawn();
                if spawned.is_ok() {
                    app.exit(0);
                }
            }
        }
    });
}

fn diagnostic_tail() -> Vec<String> {
    let log_dir = dirs::data_local_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("com.claudecode.launcher")
        .join("logs");
    let mut lines = Vec::new();
    let Ok(entries) = fs::read_dir(log_dir) else {
        return lines;
    };
    for entry in entries.flatten() {
        let Ok(body) = fs::read_to_string(entry.path()) else {
            continue;
        };
        lines.extend(
            body.lines()
                .filter(|line| line.contains("[diagnostics]") || line.contains("diagnostics]"))
                .map(|line| line.chars().take(500).collect::<String>()),
        );
    }
    lines
        .into_iter()
        .rev()
        .take(80)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect()
}

fn build_report(
    kind: &str,
    incident_id: &str,
    app_version: &str,
    stage: CompatibilityStage,
    samples: Vec<ProcessSnapshot>,
    note: Option<String>,
) -> DiagnosticReport {
    let settings = load_settings();
    DiagnosticReport {
        schema_version: REPORT_SCHEMA,
        incident_id: incident_id.to_string(),
        install_id: settings.install_id,
        kind: kind.to_string(),
        occurred_at: now_secs(),
        app_version: app_version.to_string(),
        os_version: System::long_os_version().unwrap_or_else(|| "Windows".to_string()),
        compatibility_stage: stage,
        samples,
        note: note.map(|value| sanitize_note(&value)),
        diagnostic_log_tail: diagnostic_tail(),
    }
}

fn sanitize_note(value: &str) -> String {
    let mut clean = value
        .chars()
        .filter(|character| !character.is_control() || *character == '\n')
        .take(1000)
        .collect::<String>();
    for marker in ["token", "api_key", "authorization", "base_url"] {
        if clean.to_ascii_lowercase().contains(marker) {
            clean = "[备注包含敏感配置关键词，已由客户端移除]".to_string();
            break;
        }
    }
    clean
}

fn fingerprint(report: &DiagnosticReport) -> String {
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    report.kind.hash(&mut hasher);
    report.app_version.hash(&mut hasher);
    format!("{:x}", hasher.finish())
}

fn is_automatic_report_kind(kind: &str) -> bool {
    matches!(
        kind,
        "webview_renderer_missing" | "rust_panic" | "tauri_startup_fatal"
    )
}

fn should_submit(report: &DiagnosticReport, automatic: bool) -> bool {
    let settings = load_settings();
    if automatic && (!settings.auto_report_enabled || !is_automatic_report_kind(&report.kind)) {
        return false;
    }
    if !automatic {
        return true;
    }
    let mut dedupe: DedupeState = read_json(&dedupe_path()).unwrap_or_default();
    let now = now_secs();
    dedupe
        .fingerprints
        .retain(|_, timestamp| now.saturating_sub(*timestamp) < DEDUPE_SECONDS);
    let key = fingerprint(report);
    if dedupe.fingerprints.contains_key(&key) {
        return false;
    }
    dedupe.fingerprints.insert(key, now);
    let _ = write_json(&dedupe_path(), &dedupe);
    true
}

fn diagnostics_endpoint() -> Option<String> {
    option_env!("CCL_DIAGNOSTICS_ENDPOINT")
        .map(str::to_string)
        .or_else(|| std::env::var("CCL_DIAGNOSTICS_ENDPOINT").ok())
        .filter(|value| value.starts_with("https://") || value.starts_with("http://127.0.0.1"))
}

fn submit_or_queue(report: DiagnosticReport, automatic: bool) {
    if !should_submit(&report, automatic) {
        return;
    }
    if let Err(error) = submit_report(&report) {
        log::warn!(target: "diagnostics", "diagnostic upload deferred: {}", error);
        queue_report(&report);
    }
}

fn queue_report(report: &DiagnosticReport) {
    let dir = pending_dir();
    let _ = fs::create_dir_all(&dir);
    let _ = write_json(&dir.join(format!("{}.json", report.incident_id)), report);
}

fn submit_report(report: &DiagnosticReport) -> Result<String, String> {
    let endpoint = diagnostics_endpoint().ok_or("diagnostics endpoint is not configured")?;
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(8))
        .build()
        .map_err(|error| error.to_string())?;
    let response = client
        .post(endpoint)
        .json(report)
        .send()
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(format!("HTTP {}", response.status()));
    }
    let result: SubmitResponse = response.json().map_err(|error| error.to_string())?;
    if !result.accepted {
        return Err("server rejected diagnostic report".to_string());
    }
    let report_id = result
        .report_id
        .unwrap_or_else(|| report.incident_id.clone());
    let mut settings = load_settings();
    settings.last_report_id = Some(report_id.clone());
    settings.last_report_kind = Some(report.kind.clone());
    settings.last_report_at = Some(now_secs());
    let _ = write_json(&settings_path(), &settings);
    Ok(report_id)
}

fn retry_pending_reports() {
    if !load_settings().auto_report_enabled {
        return;
    }
    let dir = pending_dir();
    let Ok(entries) = fs::read_dir(&dir) else {
        return;
    };
    for entry in entries.flatten().take(10) {
        let Some(report) = read_json::<DiagnosticReport>(&entry.path()) else {
            continue;
        };
        if !is_automatic_report_kind(&report.kind) {
            continue;
        }
        if submit_report(&report).is_ok() {
            let _ = fs::remove_file(entry.path());
        }
    }
}

pub fn install_panic_hook(app_version: String, stage: CompatibilityStage) {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let message = info
            .payload()
            .downcast_ref::<&str>()
            .copied()
            .or_else(|| info.payload().downcast_ref::<String>().map(String::as_str))
            .unwrap_or("native panic");
        let report = build_report(
            "rust_panic",
            &new_id("panic"),
            &app_version,
            stage,
            vec![],
            Some(message.to_string()),
        );
        // A panic hook must stay small and deterministic. Persist locally here;
        // the next healthy launch retries the upload after the first page loads.
        if should_submit(&report, true) {
            queue_report(&report);
        }
        previous(info);
    }));
}

pub fn record_startup_fatal(app_version: &str, stage: CompatibilityStage, error: &str) {
    let report = build_report(
        "tauri_startup_fatal",
        &new_id("startup"),
        app_version,
        stage,
        vec![],
        Some(error.to_string()),
    );
    submit_or_queue(report, true);
}

pub fn record_frontend_error(message: &str) {
    let safe = sanitize_note(message);
    log::error!(target: "frontend_local_only", "{}", safe);
}

pub fn status() -> DiagnosticsStatus {
    let settings = load_settings();
    let recovery: Option<RecoveryState> = read_json(&recovery_path());
    let stage = recovery
        .map(|value| value.stage)
        .unwrap_or(CompatibilityStage::Standard);
    let pending_reports = fs::read_dir(pending_dir())
        .map(|entries| entries.flatten().count())
        .unwrap_or(0);
    DiagnosticsStatus {
        auto_report_enabled: settings.auto_report_enabled,
        compatibility_stage: stage,
        compatibility_label: stage.label().to_string(),
        log_directory: ensure_dir().to_string_lossy().to_string(),
        endpoint_configured: diagnostics_endpoint().is_some(),
        pending_reports,
        last_report_id: settings.last_report_id,
        last_report_kind: settings.last_report_kind,
        last_report_at: settings.last_report_at,
    }
}

pub fn set_auto_report_enabled(enabled: bool) -> Result<(), String> {
    let mut settings = load_settings();
    settings.auto_report_enabled = enabled;
    write_json(&settings_path(), &settings)
}

pub fn reset_compatibility() -> Result<(), String> {
    let path = recovery_path();
    if path.exists() {
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    Ok(())
}

pub fn submit_manual(app_version: &str, note: Option<String>) -> Result<String, String> {
    let recovery: Option<RecoveryState> = read_json(&recovery_path());
    let report = build_report(
        "manual_diagnostic",
        &new_id("manual"),
        app_version,
        recovery
            .map(|value| value.stage)
            .unwrap_or(CompatibilityStage::Standard),
        vec![snapshot_webview_processes(std::process::id())],
        note,
    );
    submit_report(&report)
}

#[cfg(test)]
mod tests {
    use super::{
        is_automatic_report_kind, renderer_missing_confirmed, sanitize_note, CompatibilityStage,
        ProcessSnapshot,
    };

    fn sample(browser: usize, renderer: usize) -> ProcessSnapshot {
        ProcessSnapshot {
            browser_count: browser,
            renderer_count: renderer,
            gpu_count: 1,
            utility_count: 2,
        }
    }

    #[test]
    fn renderer_failure_requires_three_unambiguous_samples() {
        assert!(renderer_missing_confirmed(&[
            sample(1, 0),
            sample(1, 0),
            sample(1, 0),
        ]));
        assert!(!renderer_missing_confirmed(&[sample(1, 0), sample(1, 0)]));
        assert!(!renderer_missing_confirmed(&[
            sample(1, 0),
            sample(1, 1),
            sample(1, 0),
        ]));
        assert!(!renderer_missing_confirmed(&[
            sample(0, 0),
            sample(0, 0),
            sample(0, 0),
        ]));
    }

    #[test]
    fn compatibility_fallback_is_bounded_to_two_restarts() {
        assert_eq!(
            CompatibilityStage::Standard.next(),
            Some(CompatibilityStage::NoSandbox)
        );
        assert_eq!(
            CompatibilityStage::NoSandbox.next(),
            Some(CompatibilityStage::NoSandboxDisableGpu)
        );
        assert_eq!(CompatibilityStage::NoSandboxDisableGpu.next(), None);
        assert_eq!(CompatibilityStage::Standard.browser_args(), "");
        assert!(CompatibilityStage::NoSandbox
            .browser_args()
            .contains("--no-sandbox"));
        assert!(CompatibilityStage::NoSandboxDisableGpu
            .browser_args()
            .contains("--disable-gpu"));
    }

    #[test]
    fn local_note_filter_removes_sensitive_configuration() {
        assert_eq!(
            sanitize_note("authorization=Bearer secret"),
            "[备注包含敏感配置关键词，已由客户端移除]"
        );
    }

    #[test]
    fn automatic_upload_scope_is_an_explicit_allowlist() {
        assert!(is_automatic_report_kind("webview_renderer_missing"));
        assert!(is_automatic_report_kind("rust_panic"));
        assert!(is_automatic_report_kind("tauri_startup_fatal"));
        assert!(!is_automatic_report_kind("manual_diagnostic"));
        assert!(!is_automatic_report_kind("frontend_error"));
        assert!(!is_automatic_report_kind("network_error"));
    }
}
