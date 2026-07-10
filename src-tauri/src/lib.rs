use tauri::Manager;

mod commands;
mod sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Store the sidecar child process handle in app state
            app.manage(sidecar::SidecarState::default());

            #[cfg(debug_assertions)]
            {
                let window = app.get_webview_window("main").unwrap();
                window.open_devtools();
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::start_backend,
            commands::stop_backend,
            commands::get_backend_status,
            commands::select_directory,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
