mod services;
mod commands;
mod models;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Clear CLAUDECODE env var so child processes (claude CLI, bridge agents)
    // don't think they're running inside a nested Claude Code session.
    std::env::remove_var("CLAUDECODE");

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            #[cfg(desktop)]
            app.handle().plugin(tauri_plugin_updater::Builder::new().build())?;
            Ok(())
        })
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Stop mobot-bridge process when app window is destroyed
                services::BridgeManager::stop_all();
            }
        })
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
            // Onboarding commands
            commands::get_onboarding_status,
            commands::set_onboarding_completed,
            // Mobot bridge management commands
            commands::detect_mobot_installation,
            commands::install_mobot_bridge,
            commands::check_mobot_deps_installed,
            commands::detect_python,
            commands::install_mobot_deps,
            commands::start_mobot_service,
            commands::stop_mobot_service,
            commands::check_mobot_health,
            commands::get_mobot_status,
            commands::get_mobot_logs,
            // Claude login check commands
            commands::check_claude_login,
            commands::launch_claude_for_login,
            // Utility commands
            commands::get_hostname,
            commands::get_username,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
