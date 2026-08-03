use tauri::{Emitter, Manager};

mod commands;
mod sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Register the sidecar state so commands can access it.
            app.manage(sidecar::SidecarState::default());

            // A completed shell remains usable while the sidecar is stopped.
            // It is restarted by the webview before the next transport attempt.
            let idle_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut idle_since: Option<std::time::Instant> = None;
                loop {
                    tokio::time::sleep(std::time::Duration::from_secs(15)).await;
                    let state = idle_handle.state::<sidecar::SidecarState>();
                    if !sidecar::is_running(&state) {
                        idle_since = None;
                        continue;
                    }
                    if sidecar::can_idle_shutdown(&state).await {
                        let since = idle_since.get_or_insert_with(std::time::Instant::now);
                        if since.elapsed() >= std::time::Duration::from_secs(60) {
                            if let Err(error) = sidecar::stop(state).await {
                                eprintln!("[argus] idle stop failed: {error}");
                            } else {
                                let _ = idle_handle.emit("argus://sidecar-stopped", "idle");
                            }
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
        .build(tauri::generate_context!())
        .expect("error while running tauri application");
    app.run(|app_handle, event| {
        if let tauri::RunEvent::ExitRequested { code, api, .. } = event {
            let state = app_handle.state::<sidecar::SidecarState>();
            if sidecar::has_lifecycle_activity(&state) {
                api.prevent_exit();
                let exit_handle = app_handle.clone();
                tauri::async_runtime::spawn(async move {
                    let state = exit_handle.state::<sidecar::SidecarState>();
                    if sidecar::stop(state).await.is_err() {
                        eprintln!("[argus] backend stop fallback failed");
                    }
                    exit_handle.exit(code.unwrap_or(0));
                });
            }
        }
    });
}
