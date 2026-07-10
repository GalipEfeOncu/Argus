use tauri::State;
use crate::sidecar::SidecarState;

/// Start the Python FastAPI backend as a sidecar process
#[tauri::command]
pub async fn start_backend(
    app: tauri::AppHandle,
    state: State<'_, SidecarState>,
) -> Result<String, String> {
    crate::sidecar::start(app, state).await
}

/// Stop the Python FastAPI backend sidecar
#[tauri::command]
pub async fn stop_backend(
    state: State<'_, SidecarState>,
) -> Result<(), String> {
    crate::sidecar::stop(state).await
}

/// Check if the backend is running
#[tauri::command]
pub async fn get_backend_status(
    state: State<'_, SidecarState>,
) -> Result<bool, String> {
    Ok(crate::sidecar::is_running(&state))
}

/// Open a native folder picker dialog and return the selected path
#[tauri::command]
pub async fn select_directory(app: tauri::AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    let dir = app
        .dialog()
        .file()
        .set_title("Select Project Directory")
        .blocking_pick_folder();

    Ok(dir.map(|p| p.to_string()))
}
