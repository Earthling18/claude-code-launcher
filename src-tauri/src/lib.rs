mod services;
mod commands;
mod models;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Clear CLAUDECODE env var so child processes (claude CLI, bridge agents)
    // don't think they're running inside a nested Claude Code session.
    std::env::remove_var("CLAUDECODE");

    // Ensure localhost/127.0.0.1 bypasses HTTP proxy (WebView2 reads env vars)
    let no_proxy = std::env::var("NO_PROXY").unwrap_or_default();
    if !no_proxy.contains("127.0.0.1") {
        let new_val = if no_proxy.is_empty() {
            "127.0.0.1,localhost".to_string()
        } else {
            format!("{},127.0.0.1,localhost", no_proxy)
        };
        std::env::set_var("NO_PROXY", &new_val);
        std::env::set_var("no_proxy", &new_val);
    }

    // Windows: disable WebView2 GPU compositing as a fallback for the black-screen
    // hang seen on some machines (e.g. AMD integrated graphics with buggy factory
    // drivers). The launcher UI is lightweight, so software rendering is imperceptible,
    // and this avoids the deterministic blank-render + frozen-window failure mode.
    // Respect an existing value so power users can still override.
    #[cfg(windows)]
    if std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").is_err() {
        std::env::set_var(
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            "--disable-gpu --disable-gpu-compositing",
        );
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            #[cfg(desktop)]
            app.handle().plugin(tauri_plugin_updater::Builder::new().build())?;

            // macOS: cleanup old / duplicate app bundles on launch.
            //   - Old branding: "Mobot Launcher.app" / "Claude Code Launcher.app"
            //   - Finder "Keep Both" duplicates: "CC 启动器 2.app", "CC 启动器 3.app", …
            //     (created when users click "Keep Both" instead of "Replace" while
            //      drag-installing a same-named DMG over an existing copy)
            #[cfg(target_os = "macos")]
            {
                use regex::Regex;

                let mut paths: Vec<std::path::PathBuf> = Vec::new();
                let app_dirs: Vec<std::path::PathBuf> = {
                    let mut v = vec![std::path::PathBuf::from("/Applications/")];
                    if let Some(home) = dirs::home_dir() {
                        v.push(home.join("Applications/"));
                    }
                    v
                };

                // Explicit old-name targets
                let old_names = ["Mobot Launcher.app", "Claude Code Launcher.app"];
                for name in old_names {
                    for dir in &app_dirs {
                        paths.push(dir.join(name));
                    }
                }

                // Pattern-match "CC 启动器 N.app" duplicates (where N >= 2)
                let dup_re = Regex::new(r"^CC 启动器 \d+\.app$").ok();
                if let Some(re) = dup_re {
                    for dir in &app_dirs {
                        if let Ok(entries) = std::fs::read_dir(dir) {
                            for entry in entries.flatten() {
                                if let Some(name) = entry.file_name().to_str() {
                                    if re.is_match(name) {
                                        paths.push(entry.path());
                                    }
                                }
                            }
                        }
                    }
                }

                for old_app in &paths {
                    if old_app.exists() {
                        log::info!("Cleaning up app bundle: {}", old_app.display());
                        if let Err(e) = std::fs::remove_dir_all(old_app) {
                            log::warn!("Failed to remove app bundle {}: {}", old_app.display(), e);
                        }
                    }
                }
            }

            Ok(())
        })
        .on_window_event(|_window, _event| {})
        .invoke_handler(tauri::generate_handler![
            commands::check_nodejs,
            commands::check_claude,
            commands::check_gitbash,
            commands::check_nodejs_with_update,
            commands::check_claude_with_update,
            commands::check_gitbash_with_update,
            commands::refresh_system_path,
            commands::install_nodejs,
            commands::update_nodejs,
            commands::install_claude,
            commands::update_claude,
            commands::install_gitbash,
            commands::update_gitbash,
            commands::check_codex,
            commands::check_codex_with_update,
            commands::install_codex,
            commands::update_codex,
            commands::reinstall_claude,
            commands::reinstall_codex,
            commands::check_skill_market,
            commands::check_skill_market_with_update,
            commands::install_skill_market,
            commands::update_claude_silent,
            commands::update_codex_silent,
            commands::launch_claude_code,
            commands::generate_powershell_command,
            commands::generate_cmd_command,
            commands::generate_bash_command,
            commands::get_platform,
            commands::save_to_settings,
            commands::reset_settings,
            commands::open_settings_file,
            commands::save_app_config,
            commands::load_app_config,
            // Project management commands
            commands::get_projects,
            commands::get_project,
            commands::create_project,
            commands::update_project,
            commands::delete_project,
            commands::launch_project,
            commands::select_directory,
            commands::generate_project_powershell_command,
            commands::generate_project_cmd_command,
            commands::generate_project_bash_command,
            commands::get_home_directory,
            commands::update_projects_order,
            commands::update_pinned_order,
            commands::toggle_project_pinned,
            // Claude login check commands
            commands::check_claude_login,
            commands::launch_claude_for_login,
            // CC config checker commands
            commands::scan_cc_config,
            commands::clean_cc_config_field,
            commands::clean_cc_config_all,
            commands::open_cc_config_file,
            commands::fix_cc_config_bom,
            commands::fix_cc_mcp_misplaced,
            commands::remove_cc_mcp_servers,
            // Portable mode commands
            commands::is_portable_mode,
            commands::get_portable_download_url,
            commands::download_and_run_installer,
            // Global presets commands
            commands::get_global_presets,
            commands::create_proxy_preset,
            commands::update_proxy_preset,
            commands::delete_proxy_preset,
            commands::count_proxy_preset_refs,
            commands::create_model_preset,
            commands::update_model_preset,
            commands::delete_model_preset,
            commands::count_model_preset_refs,
            commands::probe_model_endpoint,
            commands::get_last_used_project_config,
            commands::set_last_used_project_config,
            commands::validate_project_launch,
            // Onboarding commands
            commands::get_onboarding_status,
            commands::set_onboarding_completed,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
