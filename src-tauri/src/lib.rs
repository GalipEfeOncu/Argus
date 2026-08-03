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

            // A completed shell remains usable while the sidecar is stopped.
            // It is restarted by the webview before the next transport attempt.
            let idle_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut idle_since: Option<std::time::Instant> = None;
                loop {
                    tokio::time::sleep(std::time::Duration::from_secs(15)).await;
                    let state = idle_handle.state::<sidecar::SidecarState>();
                    if !sidecar::is_running(&state) { idle_since = None; continue; }
                    if sidecar::can_idle_shutdown().await {
                        let since = idle_since.get_or_insert_with(std::time::Instant::now);
                        if since.elapsed() >= std::time::Duration::from_secs(60) {
                            if let Err(error) = sidecar::stop(state).await { eprintln!("[argus] idle stop failed: {error}"); }
                            idle_since = None;
                        }
                    } else {
                        idle_since = None;
                    }
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
            commands::credential_store_available,
            commands::store_provider_credential,
            commands::refresh_provider_credential,
            commands::delete_provider_credential,
            commands::remove_provider_credential,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
