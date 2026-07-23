use std::process::Command;

pub struct Installer;

/// Webank skill marketplace — download a zip and extract to ~/.claude/skills/skill-market/
const SKILL_MARKET_NAME: &str = "skill-market";
const SKILL_MARKET_SERVER: &str = "https://uat.prophecis.bdap.weoa.com";
/// Hard timeout: install should finish in seconds on intranet; otherwise we skip.
const SKILL_MARKET_TIMEOUT_SECS: u64 = 15;
/// Update probe must fail fast for external users with no intranet access.
const SKILL_MARKET_PROBE_TIMEOUT_SECS: u64 = 3;
/// Server response metadata saved at install time, used to detect package updates.
const SKILL_MARKET_META_FILE: &str = ".cc-launcher-meta.json";

impl Installer {
    /// Check if skill-market is installed by looking for files inside the target dir.
    pub fn check_skill_market() -> crate::services::dependency_checker::DependencyStatus {
        use crate::services::dependency_checker::DependencyStatus;
        let dest = match Self::skill_market_dir() {
            Some(p) => p,
            None => return DependencyStatus {
                installed: false,
                version: None,
                meets_requirement: false,
                latest_version: None,
                update_available: false,
                error: Some("无法解析用户主目录".to_string()),
            },
        };
        let installed = dest.exists()
            && std::fs::read_dir(&dest)
                .map(|mut rd| rd.next().is_some())
                .unwrap_or(false);
        DependencyStatus {
            installed,
            version: if installed { Some("已安装".to_string()) } else { None },
            meets_requirement: installed,
            latest_version: None,
            update_available: false,
            error: None,
        }
    }

    /// Synchronous install: download zip + extract. Returns Err on timeout / network / extract failure.
    /// Caller can choose to mark the step as `skipped` rather than `error` on failure
    /// since this is a best-effort intranet-only resource.
    pub fn install_skill_market() -> Result<(), String> {
        let dest = Self::skill_market_dir().ok_or("无法解析用户主目录")?;
        std::fs::create_dir_all(&dest)
            .map_err(|e| format!("创建目录失败: {}", e))?;

        let url = format!(
            "{}/cc/v2/plugin-guest/nameDown?pluginName={}",
            SKILL_MARKET_SERVER, SKILL_MARKET_NAME
        );

        // Build a client that mirrors the doc's `curl -skL --noproxy "*"`:
        //   - danger_accept_invalid_certs (-k)
        //   - timeout cap
        //   - no_proxy() to bypass system proxy (intranet endpoint)
        //   - redirect follow is reqwest default (-L)
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(SKILL_MARKET_TIMEOUT_SECS))
            .danger_accept_invalid_certs(true)
            .no_proxy()
            .build()
            .map_err(|e| format!("HTTP client 初始化失败: {}", e))?;

        let resp = client
            .get(&url)
            .header("User-Agent", "CCLauncher")
            .send()
            .map_err(|e| format!("下载失败: {}", e))?;

        if !resp.status().is_success() {
            return Err(format!("服务器返回 HTTP {}", resp.status()));
        }
        let meta = Self::headers_to_meta(resp.headers());
        let bytes = resp.bytes().map_err(|e| format!("读取响应失败: {}", e))?;

        // Write to a temp zip then extract — `zip::ZipArchive` needs Read+Seek.
        let tmp = std::env::temp_dir().join(format!("{}.zip", SKILL_MARKET_NAME));
        std::fs::write(&tmp, &bytes).map_err(|e| format!("写临时 zip 失败: {}", e))?;

        let file = std::fs::File::open(&tmp).map_err(|e| format!("打开临时 zip 失败: {}", e))?;
        let mut archive = zip::ZipArchive::new(file)
            .map_err(|e| format!("解析 zip 失败: {}", e))?;
        archive.extract(&dest).map_err(|e| format!("解压失败: {}", e))?;

        let _ = std::fs::remove_file(&tmp);

        // Record server metadata so later checks can detect a new package version
        if let Some(meta) = meta {
            let _ = std::fs::write(
                dest.join(SKILL_MARKET_META_FILE),
                serde_json::to_vec(&meta).unwrap_or_default(),
            );
        }
        Ok(())
    }

    /// Probe the intranet server for a newer skill-market package by comparing
    /// response headers (ETag / Last-Modified / Content-Length) against the meta
    /// recorded at install time. Best-effort: any network failure (external users
    /// have no route to the intranet) silently returns the plain local status.
    pub async fn check_skill_market_with_update() -> crate::services::dependency_checker::DependencyStatus {
        let mut status = Self::check_skill_market();
        if !status.installed {
            return status;
        }

        let Ok(client) = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(SKILL_MARKET_PROBE_TIMEOUT_SECS))
            .danger_accept_invalid_certs(true)
            .no_proxy()
            .build()
        else {
            return status;
        };

        let url = format!(
            "{}/cc/v2/plugin-guest/nameDown?pluginName={}",
            SKILL_MARKET_SERVER, SKILL_MARKET_NAME
        );

        // Try HEAD first; the download endpoint may not support it (the zip can be
        // packed on demand), so fall back to GET and drop the response before the
        // body is read — send() resolves once headers arrive.
        let mut remote_meta = None;
        if let Ok(resp) = client.head(&url).header("User-Agent", "CCLauncher").send().await {
            if resp.status().is_success() {
                remote_meta = Self::headers_to_meta(resp.headers());
            } else if let Ok(resp) = client.get(&url).header("User-Agent", "CCLauncher").send().await {
                if resp.status().is_success() {
                    remote_meta = Self::headers_to_meta(resp.headers());
                }
            }
        }
        let Some(remote_meta) = remote_meta else {
            return status;
        };

        let local_meta = Self::skill_market_dir()
            .map(|d| d.join(SKILL_MARKET_META_FILE))
            .and_then(|p| std::fs::read(p).ok())
            .and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok());

        // No local meta (installed by an older launcher) counts as outdated:
        // one refresh re-downloads and records the meta.
        let outdated = match &local_meta {
            Some(local) => !Self::meta_matches(local, &remote_meta),
            None => true,
        };
        if outdated {
            status.update_available = true;
            status.latest_version = Some("可更新".to_string());
        }
        status
    }

    /// Compare only fields present on BOTH sides — HEAD and GET responses may
    /// expose different header sets (e.g. no Content-Length on HEAD). If nothing
    /// is comparable, assume up-to-date rather than nagging with false positives.
    fn meta_matches(local: &serde_json::Value, remote: &serde_json::Value) -> bool {
        for key in ["etag", "last_modified", "content_length"] {
            let l = local.get(key).and_then(|v| v.as_str());
            let r = remote.get(key).and_then(|v| v.as_str());
            if let (Some(l), Some(r)) = (l, r) {
                if l != r {
                    return false;
                }
            }
        }
        // No overlapping fields → nothing to judge by; treat as up-to-date
        true
    }

    /// Extract identity headers into a comparable JSON value. Returns None when
    /// the server provides nothing usable to compare.
    fn headers_to_meta(headers: &reqwest::header::HeaderMap) -> Option<serde_json::Value> {
        let get = |name: reqwest::header::HeaderName| {
            headers
                .get(name)
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        };
        let etag = get(reqwest::header::ETAG);
        let last_modified = get(reqwest::header::LAST_MODIFIED);
        let content_length = get(reqwest::header::CONTENT_LENGTH);
        if etag.is_none() && last_modified.is_none() && content_length.is_none() {
            return None;
        }
        Some(serde_json::json!({
            "etag": etag,
            "last_modified": last_modified,
            "content_length": content_length,
        }))
    }

    fn skill_market_dir() -> Option<std::path::PathBuf> {
        dirs::home_dir().map(|h| h.join(".claude").join("skills").join(SKILL_MARKET_NAME))
    }

    /// Silent in-place npm update used by background auto-update — no terminal
    /// window, unlike update_claude/update_codex which show progress to the user.
    ///
    /// Automatic updates are skipped while Clash is active or a package
    /// executable is running. Manual install/update/reinstall commands do not
    /// use this function and remain available to the user.
    pub async fn npm_update_silent(package: &str) -> Result<(), String> {
        #[cfg(windows)]
        {
            if Self::clash_is_running().await {
                return Err("检测到 Clash 正在运行，跳过本次自动更新".to_string());
            }

            if let Some(pkg_dir) = Self::npm_global_package_dir(package).await {
                let mut exes = Vec::new();
                Self::collect_package_exes(&pkg_dir, 0, &mut exes);
                if let Some(busy) = exes.iter().find(|e| Self::exe_in_use(e)) {
                    return Err(format!(
                        "{} 正在运行，跳过本次自动更新",
                        busy.display()
                    ));
                }
            }
        }

        Self::run_npm_install_silent(package).await
    }

    #[cfg(windows)]
    async fn clash_is_running() -> bool {
        let Ok(output) = tokio::process::Command::new("tasklist.exe")
            .args(["/FO", "CSV", "/NH"])
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .output()
            .await
        else {
            return false;
        };

        let processes = String::from_utf8_lossy(&output.stdout).to_ascii_lowercase();
        [
            "clash.exe",
            "clash-verge.exe",
            "clash-verge-service.exe",
            "clash-core-service.exe",
            "verge-mihomo.exe",
            "mihomo.exe",
        ]
        .iter()
        .any(|name| processes.contains(name))
    }

    #[allow(unused_variables)]
    async fn run_npm_install_silent(package: &str) -> Result<(), String> {
        let pkg = format!("{}@latest", package);

        #[cfg(windows)]
        let mut cmd = {
            let mut c = tokio::process::Command::new("cmd");
            c.args(["/c", "npm", "install", "-g", &pkg]);
            c.creation_flags(0x08000000); // CREATE_NO_WINDOW
            c
        };

        #[cfg(target_os = "macos")]
        let mut cmd = {
            let extended_path = crate::services::dependency_checker::get_macos_extended_path();
            let mut c = tokio::process::Command::new("sh");
            c.args(["-c", &format!("PATH='{}' npm install -g {}", extended_path, pkg)]);
            c
        };

        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            return Err("不支持的操作系统".to_string());
        }

        #[cfg(any(windows, target_os = "macos"))]
        {
            let output = tokio::time::timeout(std::time::Duration::from_secs(300), cmd.output())
                .await
                .map_err(|_| "npm 更新超时".to_string())?
                .map_err(|e| format!("npm 执行失败: {}", e))?;
            if output.status.success() {
                Ok(())
            } else {
                Err(format!(
                    "npm 更新失败: {}",
                    String::from_utf8_lossy(&output.stderr)
                ))
            }
        }
    }

    /// Resolve a globally installed npm package's directory via `npm root -g`
    /// (handles non-default prefixes like nvm-windows). None if npm is missing
    /// or the package isn't installed.
    #[cfg(windows)]
    async fn npm_global_package_dir(package: &str) -> Option<std::path::PathBuf> {
        let out = tokio::process::Command::new("cmd")
            .args(["/c", "npm", "root", "-g"])
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .output()
            .await
            .ok()?;
        if !out.status.success() {
            return None;
        }
        let root = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if root.is_empty() {
            return None;
        }
        let mut dir = std::path::PathBuf::from(root);
        for part in package.split('/') {
            dir.push(part);
        }
        dir.is_dir().then_some(dir)
    }

    /// Recursively collect .exe files under an npm package dir (bounded depth —
    /// enough for bin/ and vendor/ layouts without walking huge trees).
    #[cfg(windows)]
    pub(crate) fn collect_package_exes(
        dir: &std::path::Path,
        depth: u8,
        out: &mut Vec<std::path::PathBuf>,
    ) {
        // Codex keeps its native binaries several levels below the wrapper
        // package (node_modules/@openai/.../vendor/<triple>/bin).
        if depth > 8 {
            return;
        }
        let Ok(rd) = std::fs::read_dir(dir) else { return };
        for entry in rd.flatten() {
            let p = entry.path();
            if p.is_dir() {
                Self::collect_package_exes(&p, depth + 1, out);
            } else if p
                .extension()
                .and_then(|e| e.to_str())
                .map(|e| e.eq_ignore_ascii_case("exe"))
                .unwrap_or(false)
            {
                out.push(p);
            }
        }
    }

    /// True if the exe looks truncated/corrupted: zero-length or missing the
    /// "MZ" DOS header — the exact condition that makes Windows show the
    /// misleading "不支持的 16 位应用程序" dialog.
    #[cfg(windows)]
    pub(crate) fn exe_corrupted(path: &std::path::Path) -> bool {
        use std::io::Read;
        let Ok(mut f) = std::fs::File::open(path) else { return true };
        let mut magic = [0u8; 2];
        match f.read_exact(&mut magic) {
            Ok(()) => &magic != b"MZ",
            Err(_) => true, // shorter than 2 bytes
        }
    }

    /// True if the exe is locked by a running process. A running image cannot
    /// be opened for write (ERROR_SHARING_VIOLATION), which is exactly the
    /// condition under which npm cannot safely replace the file.
    #[cfg(windows)]
    pub(crate) fn exe_in_use(path: &std::path::Path) -> bool {
        match std::fs::OpenOptions::new().write(true).open(path) {
            Ok(_) => false,
            Err(e) => matches!(e.raw_os_error(), Some(32) | Some(33)),
        }
    }
}

#[cfg(all(test, windows))]
mod native_exe_tests {
    use super::Installer;
    use std::path::PathBuf;

    fn temp_dir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("ccl-test-{}-{}", name, std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn detects_corrupted_exes() {
        let d = temp_dir("corrupt");

        let empty = d.join("empty.exe");
        std::fs::File::create(&empty).unwrap();
        assert!(Installer::exe_corrupted(&empty), "0-byte exe must be corrupted");

        let garbage = d.join("garbage.exe");
        std::fs::write(&garbage, b"\x00\x01junk").unwrap();
        assert!(Installer::exe_corrupted(&garbage), "non-MZ header must be corrupted");

        let valid = d.join("valid.exe");
        std::fs::write(&valid, b"MZ\x90\x00rest").unwrap();
        assert!(!Installer::exe_corrupted(&valid), "MZ header must pass");

        let real = PathBuf::from(r"C:\Windows\System32\cmd.exe");
        assert!(!Installer::exe_corrupted(&real), "real system exe must pass");

        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn collects_exes_with_bounded_depth() {
        let d = temp_dir("collect");
        std::fs::create_dir_all(d.join("bin")).unwrap();
        std::fs::write(d.join("bin").join("a.exe"), b"MZ").unwrap();
        std::fs::write(d.join("TOP.EXE"), b"MZ").unwrap();
        std::fs::write(d.join("bin").join("readme.txt"), b"x").unwrap();
        let deep = d
            .join("1")
            .join("2")
            .join("3")
            .join("4")
            .join("5")
            .join("6")
            .join("7")
            .join("8")
            .join("9");
        std::fs::create_dir_all(&deep).unwrap();
        std::fs::write(deep.join("deep.exe"), b"MZ").unwrap();

        let mut out = Vec::new();
        Installer::collect_package_exes(&d, 0, &mut out);
        let names: Vec<String> = out
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().to_lowercase())
            .collect();
        assert!(names.contains(&"a.exe".to_string()));
        assert!(names.contains(&"top.exe".to_string()), "extension match must be case-insensitive");
        assert!(!names.contains(&"deep.exe".to_string()), "depth cap must stop the walk");
        assert!(!names.iter().any(|n| n.ends_with(".txt")));

        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn detects_running_exe_as_in_use() {
        // The test binary itself is executing, so its image is write-locked —
        // same situation as a running claude.exe during an update.
        let me = std::env::current_exe().unwrap();
        assert!(Installer::exe_in_use(&me), "running exe must be in use");

        // An identical copy that isn't running is replaceable.
        let d = temp_dir("inuse");
        let copy = d.join("copy.exe");
        std::fs::copy(&me, &copy).unwrap();
        assert!(!Installer::exe_in_use(&copy), "non-running copy must not be in use");
        let _ = std::fs::remove_dir_all(&d);
    }

}

impl Installer {
    pub fn install_nodejs() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_nodejs_install_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_nodejs_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_nodejs() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_nodejs_update_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_nodejs_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn install_claude() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_claude_install_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_claude_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_claude() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_claude_update_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_claude_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn install_codex() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_codex_install_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_codex_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_codex() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_codex_update_script_windows();
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_codex_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    /// Reinstall Claude Code: uninstall + install in one terminal session.
    /// This fixes broken installations (missing shim, partial install, npm cache issues).
    pub fn reinstall_claude() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_reinstall_script_windows("@anthropic-ai/claude-code", "Claude Code");
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_reinstall_script_macos("@anthropic-ai/claude-code", "Claude Code");
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    /// Reinstall Codex: uninstall + install in one terminal session.
    pub fn reinstall_codex() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_reinstall_script_windows("@openai/codex", "Codex CLI");
            Self::execute_cmd_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_reinstall_script_macos("@openai/codex", "Codex CLI");
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    #[cfg(windows)]
    fn generate_reinstall_script_windows(pkg: &str, label: &str) -> String {
        // IMPORTANT — keep this script ASCII-only:
        //   1. The bat file is written as UTF-8 by Rust. Windows cmd reads bat files using
        //      the system code page (cp936 on Chinese Windows). UTF-8 bytes get
        //      misinterpreted, breaking script parsing — cmd may silently abort
        //      ("黑屏啥都没有" symptom). chcp 65001 does NOT fix this; it only affects
        //      output rendering, not how the bat file itself is decoded.
        //   2. npm on Windows is `npm.cmd`. Calling another batch from a batch WITHOUT
        //      `call` causes the parent batch to exit early. Always use `call npm ...`.
        format!(
            r#"@echo off
color 0F
title Reinstall {label}
echo.
echo ============================================
echo   Reinstall {label}
echo   {pkg}
echo ============================================
echo.

where npm >nul 2>nul
if %errorlevel% neq 0 (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        set "NPM_CMD=C:\Program Files\nodejs\npm.cmd"
    ) else (
        echo [ERROR] npm not found. Please install Node.js first.
        echo.
        pause
        exit /b 1
    )
) else (
    set "NPM_CMD=npm"
)

echo [Step 1/2] Uninstalling existing version...
echo ^> %NPM_CMD% uninstall -g {pkg}
echo.
call %NPM_CMD% uninstall -g {pkg}
echo.
echo --------------------------------------------
echo.

echo [Step 2/2] Installing fresh copy...
echo ^> %NPM_CMD% install -g {pkg}@latest
echo.
call %NPM_CMD% install -g {pkg}@latest
set RESULT=%errorlevel%
echo.

echo ============================================
if %RESULT% equ 0 (
    echo   [OK] {label} reinstall completed!
) else (
    echo   [FAILED] Reinstall failed ^(exit code %RESULT%^).
    echo   Check the npm error messages above.
)
echo ============================================
echo.
pause
"#,
            pkg = pkg,
            label = label
        )
    }

    #[cfg(target_os = "macos")]
    fn generate_reinstall_script_macos(pkg: &str, label: &str) -> String {
        format!(
            r#"
echo ""
echo "============================================"
echo "  Reinstall {label}"
echo "  {pkg}"
echo "============================================"
echo ""

if ! command -v npm > /dev/null 2>&1; then
    echo "[ERROR] npm not found. Please install Node.js first."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "[Step 1/2] Uninstalling existing version..."
echo "> npm uninstall -g {pkg}"
echo ""
npm uninstall -g {pkg} || true
echo ""
echo "--------------------------------------------"
echo ""

echo "[Step 2/2] Installing fresh copy..."
echo "> npm install -g {pkg}@latest"
echo ""
npm install -g {pkg}@latest
RESULT=$?
echo ""

echo "============================================"
if [ $RESULT -eq 0 ]; then
    echo "  [OK] {label} reinstall completed!"
else
    echo "  [FAILED] Reinstall failed (exit code $RESULT)."
    echo "  Check the npm error messages above."
fi
echo "============================================"
echo ""
read -p "Press Enter to close..."
"#,
            pkg = pkg,
            label = label
        )
    }

    pub fn install_gitbash() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_gitbash_install_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_git_install_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    pub fn update_gitbash() -> Result<(), String> {
        #[cfg(windows)]
        {
            let script = Self::generate_gitbash_update_script_windows();
            Self::execute_powershell_script(&script)
        }
        #[cfg(target_os = "macos")]
        {
            let script = Self::generate_git_update_script_macos();
            Self::execute_terminal_script(&script)
        }
        #[cfg(all(not(windows), not(target_os = "macos")))]
        {
            Err("不支持的操作系统".to_string())
        }
    }

    // ==================== Windows Scripts ====================

    #[cfg(windows)]
    fn generate_nodejs_install_script_windows() -> String {
        r#"
Write-Host '正在安装 Node.js LTS...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if ($wingetCmd) {
    Write-Host '尝试使用 winget 安装...' -ForegroundColor Cyan
    Write-Host '提示:安装过程中会显示进度条,请耐心等待' -ForegroundColor Yellow
    Write-Host ''
    winget install OpenJS.NodeJS.LTS
    $wingetExitCode = $LASTEXITCODE
    Write-Host ''
    if ($wingetExitCode -eq 0) {
        Write-Host '✓ 安装成功完成!' -ForegroundColor Green
        Write-Host '按任意键关闭此窗口...'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        exit
    } elseif ($wingetExitCode -eq -1978335189 -or $wingetExitCode -eq -1978335212) {
        Write-Host 'ℹ Node.js 已安装' -ForegroundColor Cyan
        Write-Host '按任意键关闭此窗口...'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        exit
    }
    Write-Host "winget 安装失败 (exit code: $wingetExitCode)，尝试镜像下载..." -ForegroundColor Yellow
}
else {
    Write-Host 'winget 不可用，正在从镜像下载 Node.js...' -ForegroundColor Yellow
}

Write-Host ''
$mirrorBase = 'https://cdn.npmmirror.com/binaries/node/'
try {
    $indexJson = Invoke-RestMethod -Uri "${mirrorBase}index.json" -UseBasicParsing
    $ltsVersion = ($indexJson | Where-Object { $_.lts -ne $false } | Select-Object -First 1).version
    $fileName = "node-${ltsVersion}-x64.msi"
    $downloadUrl = "${mirrorBase}${ltsVersion}/${fileName}"
    $outPath = "$env:TEMP\$fileName"

    Write-Host "下载: $fileName" -ForegroundColor Cyan
    Invoke-WebRequest -Uri $downloadUrl -OutFile $outPath -UseBasicParsing
    Write-Host '下载完成，正在启动安装程序...' -ForegroundColor Green
    $proc = Start-Process -FilePath 'msiexec.exe' -ArgumentList "/i `"$outPath`" /norestart" -Wait -PassThru
    if ($proc.ExitCode -eq 0) {
        Write-Host '✓ Node.js 安装完成' -ForegroundColor Green
    } else {
        Write-Host "✗ 安装失败 (exit code: $($proc.ExitCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "下载失败: $_" -ForegroundColor Red
    Write-Host '正在打开备用下载页面...' -ForegroundColor Yellow
    Start-Process 'https://nodejs.org/en/download/'
}
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    #[cfg(windows)]
    fn generate_nodejs_update_script_windows() -> String {
        r#"
Write-Host '正在更新 Node.js...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if ($wingetCmd) {
    Write-Host '尝试使用 winget 更新...' -ForegroundColor Cyan
    winget upgrade OpenJS.NodeJS.LTS
    $wingetExitCode = $LASTEXITCODE
    if ($wingetExitCode -eq 0 -or $wingetExitCode -eq -1978335189) {
        Write-Host '✓ Node.js 更新完成' -ForegroundColor Green
        Write-Host ''
        Write-Host '按任意键关闭此窗口...'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        exit
    }
    Write-Host "winget 更新失败 (exit code: $wingetExitCode)，尝试镜像下载..." -ForegroundColor Yellow
}
else {
    Write-Host 'winget 不可用，正在从镜像下载 Node.js...' -ForegroundColor Yellow
}

Write-Host ''
$mirrorBase = 'https://cdn.npmmirror.com/binaries/node/'
try {
    $indexJson = Invoke-RestMethod -Uri "${mirrorBase}index.json" -UseBasicParsing
    $ltsVersion = ($indexJson | Where-Object { $_.lts -ne $false } | Select-Object -First 1).version
    $fileName = "node-${ltsVersion}-x64.msi"
    $downloadUrl = "${mirrorBase}${ltsVersion}/${fileName}"
    $outPath = "$env:TEMP\$fileName"

    Write-Host "下载: $fileName" -ForegroundColor Cyan
    Invoke-WebRequest -Uri $downloadUrl -OutFile $outPath -UseBasicParsing
    Write-Host '下载完成，正在启动安装程序...' -ForegroundColor Green
    $proc = Start-Process -FilePath 'msiexec.exe' -ArgumentList "/i `"$outPath`" /norestart" -Wait -PassThru
    if ($proc.ExitCode -eq 0) {
        Write-Host '✓ Node.js 更新完成' -ForegroundColor Green
    } else {
        Write-Host "✗ 安装失败 (exit code: $($proc.ExitCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "下载失败: $_" -ForegroundColor Red
    Write-Host '正在打开备用下载页面...' -ForegroundColor Yellow
    Start-Process 'https://nodejs.org/en/download/'
}
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    #[cfg(windows)]
    fn generate_claude_install_script_windows() -> String {
        r#"@echo off
echo Installing Claude Code...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @anthropic-ai/claude-code
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @anthropic-ai/claude-code
    ) else (
        echo npm not found. Please make sure Node.js is installed.
        pause
        exit /b 1
    )
)
if %errorlevel%==0 (
    echo.
    echo [OK] Installation completed!
) else (
    echo.
    echo [FAILED] Installation failed!
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_claude_update_script_windows() -> String {
        r#"@echo off
echo Updating Claude Code...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @anthropic-ai/claude-code@latest
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @anthropic-ai/claude-code@latest
    ) else (
        echo npm not found.
        pause
        exit /b 1
    )
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_codex_install_script_windows() -> String {
        r#"@echo off
echo Installing Codex CLI...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @openai/codex
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @openai/codex
    ) else (
        echo npm not found. Please make sure Node.js is installed.
        pause
        exit /b 1
    )
)
if %errorlevel%==0 (
    echo.
    echo [OK] Installation completed!
) else (
    echo.
    echo [FAILED] Installation failed!
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_codex_update_script_windows() -> String {
        r#"@echo off
echo Updating Codex CLI...
echo.
where npm >nul 2>nul
if %errorlevel%==0 (
    npm install -g @openai/codex@latest
) else (
    if exist "C:\Program Files\nodejs\npm.cmd" (
        "C:\Program Files\nodejs\npm.cmd" install -g @openai/codex@latest
    ) else (
        echo npm not found.
        pause
        exit /b 1
    )
)
echo.
pause"#.to_string()
    }

    #[cfg(windows)]
    fn generate_gitbash_install_script_windows() -> String {
        r#"
Write-Host '正在安装 Git...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if ($wingetCmd) {
    Write-Host '尝试使用 winget 安装...' -ForegroundColor Cyan
    $wingetResult = Start-Process -FilePath 'winget' -ArgumentList 'install','--id','Git.Git','-e','--source','winget' -Wait -PassThru -NoNewWindow
    if ($wingetResult.ExitCode -eq 0) {
        Write-Host '✓ Git 安装完成 (winget)' -ForegroundColor Green
        Write-Host ''
        Write-Host '按任意键关闭此窗口...'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        exit
    }
    Write-Host "winget 安装失败 (exit code: $($wingetResult.ExitCode))，尝试镜像下载..." -ForegroundColor Yellow
}
else {
    Write-Host 'winget 不可用，正在从镜像下载 Git...' -ForegroundColor Yellow
}
Write-Host ''

$mirrorBase = 'https://registry.npmmirror.com/-/binary/git-for-windows/'
try {
    $json = Invoke-RestMethod -Uri $mirrorBase -UseBasicParsing
    $latest = $json | Where-Object { $_.type -eq 'dir' -and $_.name -match '^v[\d.]+\.windows\.\d+/$' -and $_.name -notmatch 'rc' } | Sort-Object -Property date -Descending | Select-Object -First 1
    $ver = $latest.name.TrimEnd('/')
    $verNum = $ver -replace '^v' -replace '\.windows\.\d+$'
    $winSuffix = if ($ver -match '\.windows\.(\d+)$') { $Matches[1] } else { '1' }
    $fileName = if ($winSuffix -eq '1') { "Git-$verNum-64-bit.exe" } else { "Git-$verNum.$winSuffix-64-bit.exe" }
    $downloadUrl = "${mirrorBase}${ver}/${fileName}"
    $outPath = "$env:TEMP\$fileName"

    Write-Host "下载: $fileName" -ForegroundColor Cyan
    Invoke-WebRequest -Uri $downloadUrl -OutFile $outPath -UseBasicParsing
    Write-Host '下载完成，正在启动安装程序...' -ForegroundColor Green
    $proc = Start-Process -FilePath $outPath -ArgumentList '/SILENT /NORESTART' -Wait -PassThru
    if ($proc.ExitCode -eq 0) {
        Write-Host '✓ Git 安装完成' -ForegroundColor Green
    } else {
        Write-Host "✗ 安装失败 (exit code: $($proc.ExitCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "下载失败: $_" -ForegroundColor Red
    Write-Host '正在打开备用下载页面...' -ForegroundColor Yellow
    Start-Process 'https://git-scm.com/download/windows'
}
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    #[cfg(windows)]
    fn generate_gitbash_update_script_windows() -> String {
        r#"
Write-Host '正在更新 Git...' -ForegroundColor Green
Write-Host ''

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if ($wingetCmd) {
    Write-Host '尝试使用 winget 更新...' -ForegroundColor Cyan
    $wingetResult = Start-Process -FilePath 'winget' -ArgumentList 'upgrade','--id','Git.Git','-e','--source','winget' -Wait -PassThru -NoNewWindow
    if ($wingetResult.ExitCode -eq 0) {
        Write-Host '✓ Git 更新完成 (winget)' -ForegroundColor Green
        Write-Host ''
        Write-Host '按任意键关闭此窗口...'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        exit
    }
    Write-Host "winget 更新失败 (exit code: $($wingetResult.ExitCode))，尝试镜像下载..." -ForegroundColor Yellow
}
else {
    Write-Host 'winget 不可用，正在从镜像下载 Git...' -ForegroundColor Yellow
}
Write-Host ''

$mirrorBase = 'https://registry.npmmirror.com/-/binary/git-for-windows/'
try {
    $json = Invoke-RestMethod -Uri $mirrorBase -UseBasicParsing
    $latest = $json | Where-Object { $_.type -eq 'dir' -and $_.name -match '^v[\d.]+\.windows\.\d+/$' -and $_.name -notmatch 'rc' } | Sort-Object -Property date -Descending | Select-Object -First 1
    $ver = $latest.name.TrimEnd('/')
    $verNum = $ver -replace '^v' -replace '\.windows\.\d+$'
    $winSuffix = if ($ver -match '\.windows\.(\d+)$') { $Matches[1] } else { '1' }
    $fileName = if ($winSuffix -eq '1') { "Git-$verNum-64-bit.exe" } else { "Git-$verNum.$winSuffix-64-bit.exe" }
    $downloadUrl = "${mirrorBase}${ver}/${fileName}"
    $outPath = "$env:TEMP\$fileName"

    Write-Host "下载: $fileName" -ForegroundColor Cyan
    Invoke-WebRequest -Uri $downloadUrl -OutFile $outPath -UseBasicParsing
    Write-Host '下载完成，正在启动安装程序...' -ForegroundColor Green
    $proc = Start-Process -FilePath $outPath -ArgumentList '/SILENT /NORESTART' -Wait -PassThru
    if ($proc.ExitCode -eq 0) {
        Write-Host '✓ Git 更新完成' -ForegroundColor Green
    } else {
        Write-Host "✗ 安装失败 (exit code: $($proc.ExitCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "下载失败: $_" -ForegroundColor Red
    Write-Host '正在打开备用下载页面...' -ForegroundColor Yellow
    Start-Process 'https://git-scm.com/download/windows'
}
Write-Host ''
Write-Host '按任意键关闭此窗口...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"#.to_string()
    }

    // ==================== macOS Scripts ====================

    #[cfg(target_os = "macos")]
    fn generate_nodejs_install_script_macos() -> String {
        r#"
echo "正在安装 Node.js..."
echo ""

# 1. Check if node is already installed
if command -v node &> /dev/null; then
    echo "✓ Node.js 已安装:"
    node --version
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 2. Try Homebrew if available
if command -v brew &> /dev/null; then
    echo "使用 Homebrew 安装 Node.js..."
    brew install node
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ 安装成功完成!"
        node --version
    else
        echo ""
        echo "✗ Homebrew 安装失败!"
    fi
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 3. No Homebrew — install Homebrew first, then node
echo "未检测到 Homebrew，将先安装 Homebrew..."
echo ""
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add brew to PATH for current session (Apple Silicon vs Intel)
if [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -f /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

if command -v brew &> /dev/null; then
    echo ""
    echo "Homebrew 安装成功，正在安装 Node.js..."
    brew install node
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ Node.js 安装成功!"
        node --version
    else
        echo "✗ Node.js 安装失败!"
    fi
else
    echo ""
    echo "✗ Homebrew 安装失败，正在打开 Node.js 下载页面..."
    open "https://nodejs.org/en/download/"
fi

echo ""
read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_nodejs_update_script_macos() -> String {
        r#"
echo "正在更新 Node.js..."
echo ""

# Try Homebrew if available
if command -v brew &> /dev/null; then
    export HOMEBREW_NO_AUTO_UPDATE=1
    export HOMEBREW_NO_ENV_HINTS=1
    # Check if node was installed via brew
    if brew list node &> /dev/null; then
        brew upgrade node 2>/dev/null || echo "Node.js 已是最新版本"
    else
        # Node exists but not via brew — reinstall through brew to manage future updates
        echo "当前 Node.js 非 Homebrew 安装，正在通过 Homebrew 重新安装以便管理更新..."
        brew install node
    fi
    echo ""
    echo "✓ 更新完成!"
    node --version
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# No Homebrew — install Homebrew first, then upgrade
echo "未检测到 Homebrew，正在安装 Homebrew..."
echo ""
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add brew to PATH for current session (Apple Silicon vs Intel)
if [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -f /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

if command -v brew &> /dev/null; then
    echo ""
    echo "✓ Homebrew 安装成功，正在更新 Node.js..."
    brew upgrade node
    echo ""
    echo "✓ 更新完成!"
    node --version
else
    echo ""
    echo "✗ Homebrew 安装失败，正在打开 Node.js 下载页面..."
    open "https://nodejs.org/en/download/"
fi

echo ""
read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_claude_install_script_macos() -> String {
        r#"
echo "Installing Claude Code..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found. Please install Node.js first."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @anthropic-ai/claude-code

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Installation completed!"
else
    echo ""
    echo "✗ Installation failed!"
fi

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_claude_update_script_macos() -> String {
        r#"
echo "Updating Claude Code..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @anthropic-ai/claude-code@latest

echo ""
echo "✓ Update completed!"

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_codex_install_script_macos() -> String {
        r#"
echo "Installing Codex CLI..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found. Please install Node.js first."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @openai/codex

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Installation completed!"
else
    echo ""
    echo "✗ Installation failed!"
fi

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_codex_update_script_macos() -> String {
        r#"
echo "Updating Codex CLI..."
echo ""

if ! command -v npm &> /dev/null; then
    echo "✗ npm not found."
    read -p "Press Enter to close..."
    exit 1
fi

npm install -g @openai/codex@latest

echo ""
echo "✓ Update completed!"

read -p "Press Enter to close..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_git_install_script_macos() -> String {
        r#"
echo "正在安装 Git..."
echo ""

# 1. Check if git is already installed
if command -v git &> /dev/null; then
    echo "✓ Git 已安装:"
    git --version
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 2. Try xcode-select (system native way)
echo "正在通过 Xcode Command Line Tools 安装 Git..."
xcode-select --install 2>/dev/null
if [ $? -eq 0 ]; then
    echo ""
    echo "已弹出 Xcode Command Line Tools 安装窗口，请完成安装后重新检测。"
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 3. Try Homebrew if available
echo "Xcode Command Line Tools 安装失败，尝试 Homebrew..."
if command -v brew &> /dev/null; then
    export HOMEBREW_NO_AUTO_UPDATE=1
    export HOMEBREW_NO_ENV_HINTS=1
    brew install git
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ 安装成功!"
        git --version
    else
        echo "✗ 安装失败!"
    fi
    echo ""
    read -p "按回车键关闭此窗口..."
    exit 0
fi

# 4. No Homebrew — install Homebrew first, then git
echo "未检测到 Homebrew，将先安装 Homebrew..."
echo ""
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add brew to PATH for current session (Apple Silicon vs Intel)
if [ -f /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -f /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

if command -v brew &> /dev/null; then
    echo ""
    echo "Homebrew 安装成功，正在安装 Git..."
    brew install git
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ Git 安装成功!"
        git --version
    else
        echo "✗ Git 安装失败!"
    fi
else
    echo ""
    echo "✗ Homebrew 安装失败，正在打开 Git 下载页面..."
    open "https://git-scm.com/download/mac"
fi

echo ""
read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    #[cfg(target_os = "macos")]
    fn generate_git_update_script_macos() -> String {
        r#"
echo "正在更新 Git..."
echo ""

# Check if git is installed via brew
if command -v brew &> /dev/null; then
    export HOMEBREW_NO_AUTO_UPDATE=1
    export HOMEBREW_NO_ENV_HINTS=1
    if brew list git &> /dev/null; then
        brew upgrade git 2>/dev/null || echo "Git 已是最新版本"
        echo ""
        echo "✓ 更新完成!"
        git --version
        read -p "按回车键关闭此窗口..."
        exit 0
    fi
fi

# Git installed via Xcode Command Line Tools — try softwareupdate
echo "当前 Git 由 Xcode Command Line Tools 提供，正在尝试系统更新..."
softwareupdate -l 2>&1 | grep -i "command line"
if [ $? -eq 0 ]; then
    echo "发现可用更新，正在安装..."
    softwareupdate -i "$(softwareupdate -l 2>&1 | grep -i 'command line' | grep -oE '\*.*' | sed 's/^\* Label: //')" --agree-to-license 2>/dev/null
    echo ""
    echo "✓ 更新完成!"
    git --version
else
    echo "当前已是最新版本"
    echo ""
    git --version
fi

read -p "按回车键关闭此窗口..."
"#.to_string()
    }

    // ==================== Execution Functions ====================

    #[cfg(windows)]
    fn execute_powershell_script(script: &str) -> Result<(), String> {
        use std::os::windows::process::CommandExt;
        use std::io::Write;
        // Hide the launcher cmd; the visible PowerShell window is opened by `start`.
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        // Save the script to a .ps1 file so we can launch it via `start` (avoiding
        // the direct-spawn path that gets intercepted by Windows Terminal). Same
        // workaround as execute_cmd_script. Unique filename per invocation prevents
        // concurrent installs from overwriting each other's script mid-run.
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let temp_dir = std::env::temp_dir();
        let ps1_file = temp_dir.join(format!("cclauncher_install_{}.ps1", stamp));

        {
            let mut file = std::fs::File::create(&ps1_file)
                .map_err(|e| format!("无法创建临时 PS 脚本文件: {}", e))?;
            // PowerShell `-File` reads the script with the system ANSI codepage by default
            // (cp936 on Chinese Windows), which mangles UTF-8 Chinese into mojibake.
            // Writing a UTF-8 BOM first makes PowerShell auto-detect UTF-8.
            file.write_all(&[0xEF, 0xBB, 0xBF])
                .map_err(|e| format!("无法写入 PS 脚本 BOM: {}", e))?;
            file.write_all(script.as_bytes())
                .map_err(|e| format!("无法写入 PS 脚本文件: {}", e))?;
            file.sync_all().ok();
        }

        let ps1 = ps1_file.to_str().unwrap();
        // cmd /c start "" powershell -NoExit -ExecutionPolicy Bypass -File "<ps1>"
        let cmdline = format!(
            r#"/c start "" powershell -NoExit -ExecutionPolicy Bypass -File "{}""#,
            ps1
        );
        Command::new("cmd")
            .raw_arg(&cmdline)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("无法启动PowerShell: {}", e))?;

        Ok(())
    }

    #[cfg(windows)]
    fn execute_cmd_script(script: &str) -> Result<(), String> {
        use std::os::windows::process::CommandExt;
        use std::io::Write;
        // The launcher cmd itself runs hidden; the visible console is opened by `start`.
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        // Unique per invocation so concurrent installs don't overwrite each other's
        // bat file mid-run (which causes cmd to read corrupted lines like `cho.`).
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let temp_dir = std::env::temp_dir();
        let batch_file = temp_dir.join(format!("cclauncher_install_{}.bat", stamp));

        {
            let mut file = std::fs::File::create(&batch_file)
                .map_err(|e| format!("无法创建临时批处理文件: {}", e))?;
            file.write_all(script.as_bytes())
                .map_err(|e| format!("无法写入批处理文件: {}", e))?;
            file.sync_all().ok();
        } // explicit drop so the file handle is closed before cmd reads it

        // Why this command line:
        //   Direct `Command::new("cmd").creation_flags(CREATE_NEW_CONSOLE)` can be
        //   intercepted by the system's "Default Terminal Application" (Windows Terminal)
        //   and routed to a window that fails to render output. Going through `start`
        //   uses ShellExecute — the same path Explorer's double-click takes, which works
        //   reliably even when the direct-spawn path is broken.
        //
        // We build the command line via raw_arg so quoting is exact:
        //   cmd /c start "" cmd /k "C:\path\to\claude_install.bat"
        // The empty `""` is `start`'s window-title argument (omitting it would treat the
        // bat path as the title and fail to launch).
        let bat = batch_file.to_str().unwrap();
        let cmdline = format!(r#"/c start "" cmd /k "{}""#, bat);
        Command::new("cmd")
            .raw_arg(&cmdline)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("无法启动CMD: {}", e))?;

        Ok(())
    }

    #[cfg(target_os = "macos")]
    fn execute_terminal_script(script: &str) -> Result<(), String> {
        use std::io::Write;

        // Unique per invocation so concurrent installs don't overwrite each other.
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let temp_dir = std::env::temp_dir();
        let script_file = temp_dir.join(format!("cclauncher_install_{}.sh", stamp));

        let mut file = std::fs::File::create(&script_file)
            .map_err(|e| format!("无法创建临时脚本文件: {}", e))?;
        file.write_all(script.as_bytes())
            .map_err(|e| format!("无法写入脚本文件: {}", e))?;

        // Make executable
        Command::new("chmod")
            .args(&["+x", script_file.to_str().unwrap()])
            .output()
            .map_err(|e| format!("无法设置执行权限: {}", e))?;

        // Open in Terminal.app
        let apple_script = format!(
            r#"tell application "Terminal"
                activate
                do script "{}"
            end tell"#,
            script_file.display()
        );

        Command::new("osascript")
            .args(&["-e", &apple_script])
            .spawn()
            .map_err(|e| format!("无法启动Terminal: {}", e))?;

        Ok(())
    }
}
