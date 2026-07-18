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
            // Register the sidecar state so commands can access it.
            app.manage(sidecar::SidecarState::default());

            // ── Auto-start the Python backend ──────────────────────────
            // We kick off an async task immediately after the Tauri window
            // is ready.  This means the UI is responsive from the first
            // frame while the backend boots in the background.
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let state = app_handle.state::<sidecar::SidecarState>();
                match sidecar::start(app_handle.clone(), state).await {
                    Ok(msg) => println!("[argus] Backend auto-start: {msg}"),
                    Err(e) => eprintln!("[argus] Backend auto-start failed: {e}"),
                }
            });

            // ── Open DevTools in debug builds ──────────────────────────
            #[cfg(debug_assertions)]
            {
                if let Some(window) = app.get_webview_window("main") {
                    window.open_devtools();
                }
            }

            Ok(())
        })
        // ── Graceful shutdown ──────────────────────────────────────────
        // When the last window is destroyed (user clicks X), kill the
        // backend process so it doesn't linger in the background.
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let app_handle = window.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    let state = app_handle.state::<sidecar::SidecarState>();
                    if let Err(e) = sidecar::stop(state).await {
                        eprintln!("[argus] Failed to stop backend on shutdown: {e}");
                    } else {
                        println!("[argus] Backend stopped on window destroy");
                    }
                });
            }
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
