use std::sync::Mutex;
use tauri::State;
use tauri_plugin_shell::ShellExt;

/// Holds the sidecar child process handle
#[derive(Default)]
pub struct SidecarState {
    child: Mutex<Option<tauri_plugin_shell::process::CommandChild>>,
}

/// Start the Python backend sidecar on a fixed port
pub async fn start(
    app: tauri::AppHandle,
    state: State<'_, SidecarState>,
) -> Result<String, String> {
    let mut child_lock = state.child.lock().map_err(|e| e.to_string())?;

    if child_lock.is_some() {
        return Ok("Backend already running".to_string());
    }

    // In development, use the Python script directly.
    // In production, use the bundled sidecar binary.
    #[cfg(debug_assertions)]
    let cmd = app
        .shell()
        .command("python3")
        .args(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"])
        .current_dir(std::path::PathBuf::from("./backend"));

    #[cfg(not(debug_assertions))]
    let cmd = app
        .shell()
        .sidecar("argus-backend")
        .map_err(|e| e.to_string())?;

    let (mut rx, child) = cmd.spawn().map_err(|e| e.to_string())?;

    *child_lock = Some(child);

    // Spawn a task to log output
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    eprintln!("[backend stdout] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[backend stderr] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(status) => {
                    eprintln!("[backend] Process terminated with status: {:?}", status);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok("Backend started on http://127.0.0.1:8000".to_string())
}

/// Kill the sidecar process
pub async fn stop(state: State<'_, SidecarState>) -> Result<(), String> {
    let mut child_lock = state.child.lock().map_err(|e| e.to_string())?;
    if let Some(child) = child_lock.take() {
        child.kill().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Check if the sidecar is running
pub fn is_running(state: &SidecarState) -> bool {
    state
        .child
        .lock()
        .map(|g| g.is_some())
        .unwrap_or(false)
}
