//! The launcher owns runtime selection; the Python tool owns connection data.
use crate::models::PythonConnection;
use crate::services::Launcher;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    io::Read,
    path::Path,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

#[derive(Serialize, Deserialize)]
pub struct ConnectionInfo {
    pub python: String,
    pub version: String,
    pub profiles: Vec<String>,
    pub profile_labels: HashMap<String, String>,
}

pub fn validate_preset(
    name: &str,
    url: &str,
    connection: Option<&PythonConnection>,
) -> Result<(), String> {
    if name.trim().is_empty() {
        return Err("请填写名称".into());
    }
    if let Some(c) = connection {
        if !Path::new(&c.script).is_absolute() || !c.script.ends_with(".py") {
            return Err("请选择 Python 连接工具的 .py 文件（完整路径）".into());
        }
        if c.profile.is_empty()
            || !c
                .profile
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_')
        {
            return Err("方案 ID 只能包含字母、数字、横线和下划线".into());
        }
    } else if reqwest::Url::parse(url)
        .map(|u| !matches!(u.scheme(), "http" | "https") || u.host_str().is_none())
        .unwrap_or(true)
        || url.contains(['\r', '\n', '\\'])
    {
        return Err("请填写有效的 HTTP(S) 代理地址".into());
    }
    Ok(())
}

// Drain pipes while waiting and bound execution time. Do not include raw subprocess
// output in errors: selected scripts and upstream errors may contain credentials.
fn capture(mut cmd: Command, seconds: u64) -> Result<Vec<u8>, String> {
    cmd.stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    let mut child = cmd
        .spawn()
        .map_err(|_| "无法运行 Python，请检查解释器路径".to_string())?;
    let mut stdout = child.stdout.take().unwrap();
    let reader = std::thread::spawn(move || {
        let mut result = Vec::new();
        let mut buf = [0u8; 4096];
        while let Ok(n) = stdout.read(&mut buf) {
            if n == 0 {
                break;
            }
            if result.len() < 65536 {
                result.extend_from_slice(&buf[..n]);
            }
        }
        result
    });
    let started = Instant::now();
    loop {
        match child
            .try_wait()
            .map_err(|_| "无法读取运行状态".to_string())?
        {
            Some(status) => {
                let output = reader.join().unwrap_or_default();
                return if status.success() {
                    Ok(output)
                } else {
                    Err("检查未通过，请在“管理连接与分流”中查看配置和诊断".into())
                };
            }
            None if started.elapsed() > Duration::from_secs(seconds) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("检查超时。Mac 请先处理系统的文件夹访问提示，或把脚本放到用户目录下；也可用“浏览”重新选择。Windows 请检查解释器和文件权限".into());
            }
            _ => std::thread::sleep(Duration::from_millis(40)),
        }
    }
}

fn command(program: &str) -> Command {
    let mut cmd = Command::new(program);
    #[cfg(target_os = "macos")]
    cmd.env(
        "PATH",
        crate::services::dependency_checker::get_macos_extended_path(),
    );
    cmd
}

fn runtime(selected: &str) -> Result<(String, String), String> {
    let candidates: Vec<(&str, Vec<&str>)> = if !selected.trim().is_empty() {
        vec![(selected.trim(), vec![])]
    } else if cfg!(windows) {
        vec![("py", vec!["-3"]), ("python", vec![])]
    } else {
        vec![
            ("python3", vec![]),
            ("/opt/homebrew/bin/python3", vec![]),
            ("/usr/local/bin/python3", vec![]),
            ("python3.13", vec![]),
            ("python3.12", vec![]),
            ("python3.11", vec![]),
        ]
    };
    for (program, args) in candidates {
        let mut cmd = command(program);
        cmd.args(args).args(["-c", "import sys,json; assert sys.version_info >= (3,11); print(json.dumps([sys.executable,sys.version.split()[0]]))"]);
        if let Ok(data) = capture(cmd, 8) {
            if let Ok(pair) = serde_json::from_slice::<Vec<String>>(&data) {
                if pair.len() == 2 {
                    return Ok((pair[0].clone(), pair[1].clone()));
                }
            }
        }
    }
    Err("未找到可用的 Python 3.11+；请安装后重试，或填写解释器完整路径（不要填写命令参数）".into())
}

fn tool_prefix(c: &PythonConnection) -> Result<Vec<String>, String> {
    validate_preset("connection", "", Some(c))?;
    if !Path::new(&c.script).is_file() {
        return Err("连接脚本不存在，请重新选择 .py 文件".into());
    }
    let (python, _) = runtime(&c.python)?;
    Ok(vec![
        python,
        c.script.clone(),
        "--profile".into(),
        c.profile.clone(),
    ])
}

pub fn prepare_network(config: &mut HashMap<String, String>) -> Result<(), String> {
    if let Some(raw) = config.get("PYTHON_CONNECTION") {
        let c: PythonConnection = serde_json::from_str(raw).map_err(|_| "连接方案格式无效")?;
        let mut prefix = tool_prefix(&c)?;
        prefix.extend(["run".into(), "--".into()]);
        config.insert(
            "NETWORK_PREFIX_JSON".into(),
            serde_json::to_string(&prefix).unwrap(),
        );
        config.remove("HTTP_PROXY");
        config.remove("HTTPS_PROXY");
    }
    Ok(())
}

#[tauri::command]
pub async fn connection_info(connection: PythonConnection) -> Result<ConnectionInfo, String> {
    tokio::task::spawn_blocking(move || {
        let (python, version) = runtime(&connection.python)?;
        log::info!("connection Python runtime: {} ({})", python, version);
        let (profiles, profile_labels) = if connection.script.trim().is_empty() {
            (vec![], HashMap::new())
        } else {
            let mut cmd = command(&python);
            cmd.args([&connection.script, "profiles", "--json"]);
            let data = capture(cmd, 10)
                .map_err(|reason| format!("方案列表读取失败：{}；解释器 {}", reason, python))?;
            #[derive(Deserialize)]
            struct Profiles {
                protocol: u32,
                profiles: Vec<String>,
                #[serde(default)]
                profile_labels: HashMap<String, String>,
            }
            let list: Profiles = serde_json::from_slice(&data)
                .map_err(|_| "脚本不支持连接管理接口，请选择新版 ai-connection.py")?;
            if list.protocol != 1 {
                return Err("连接工具接口版本不兼容".into());
            }
            (list.profiles, list.profile_labels)
        };
        Ok(ConnectionInfo {
            python,
            version,
            profiles,
            profile_labels,
        })
    })
    .await
    .map_err(|_| "检查任务失败".to_string())?
}

#[tauri::command]
pub async fn connection_action(connection: PythonConnection, action: String) -> Result<(), String> {
    if action != "menu" && action != "doctor" {
        return Err("不支持的操作".into());
    }
    tokio::task::spawn_blocking(move || {
        let mut args = tool_prefix(&connection)?;
        let mut actual = action;
        if actual == "menu" {
            let mut probe = command(&args[0]);
            probe.args([&connection.script, "profiles", "--json"]);
            if let Ok(data) = capture(probe, 10) {
                if let Ok(value) = serde_json::from_slice::<serde_json::Value>(&data) {
                    if value.get("capabilities").and_then(|v| v.as_array())
                        .is_some_and(|v| v.iter().any(|x| x.as_str() == Some("web"))) {
                        actual = "web".into();
                    }
                }
            }
        }
        args.push(actual);
        Launcher::launch_connection_tool(args)
    })
    .await
    .map_err(|_| "启动任务失败".to_string())?
}

#[tauri::command]
pub async fn select_connection_file(
    app_handle: tauri::AppHandle,
    script: bool,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let mut dialog = app_handle.dialog().file().set_title(if script {
        "选择 ai-connection.py"
    } else {
        "选择 Python 解释器"
    });
    if script {
        dialog = dialog.add_filter("Python", &["py"]);
    }
    Ok(dialog.blocking_pick_file().map(|p| p.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn old_presets_remain_url_mode() {
        let preset: crate::models::ProxyPreset =
            serde_json::from_str(r#"{"id":"old","name":"Old","url":"http://127.0.0.1:7890"}"#)
                .unwrap();
        assert!(preset.python_connection.is_none());
    }
    #[test]
    fn profile_reference_cannot_traverse_directories() {
        let c = PythonConnection {
            python: String::new(),
            script: std::env::current_dir()
                .unwrap()
                .join("ai-connection.py")
                .to_string_lossy()
                .into(),
            profile: "../credentials".into(),
        };
        assert!(validate_preset("test", "", Some(&c)).is_err());
    }
}
