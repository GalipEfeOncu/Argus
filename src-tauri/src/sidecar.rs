use std::sync::Mutex;
use tauri::State;
use tauri_plugin_shell::ShellExt;

/// Holds the sidecar child process handle.
#[derive(Default)]
pub struct SidecarState {
    child: Mutex<Option<tauri_plugin_shell::process::CommandChild>>,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/// Check whether something is already listening on a local TCP port.
fn is_port_in_use(port: u16) -> bool {
    std::net::TcpStream::connect(format!("127.0.0.1:{}", port)).is_ok()
}

/// Poll the port at 250 ms intervals until it responds or timeout elapses.
async fn wait_for_backend(port: u16, timeout_secs: u64) -> bool {
    let deadline =
        std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    while std::time::Instant::now() < deadline {
        if is_port_in_use(port) {
            return true;
        }
        tokio::time::sleep(std::time::Duration::from_millis(250)).await;
    }
    false
}

/// Resolve the `uv` binary path.
///
/// Tauri spawns processes with a minimal environment — `~/.local/bin` is often
/// not in PATH.  We probe the most common install locations in order.
fn find_uv() -> Option<std::path::PathBuf> {
    // 1. Check PATH first (works in most shell-launched environments)
    if let Ok(path) = which_uv_from_path() {
        return Some(path);
    }
    // 2. Fallback: well-known install locations
    let candidates = [
        // uv installer default (Linux/macOS)
        dirs_next_home().join(".local/bin/uv"),
        dirs_next_home().join(".cargo/bin/uv"),
        std::path::PathBuf::from("/usr/local/bin/uv"),
        std::path::PathBuf::from("/usr/bin/uv"),
        std::path::PathBuf::from("/opt/homebrew/bin/uv"),
    ];
    candidates.into_iter().find(|p| p.exists())
}

fn which_uv_from_path() -> Result<std::path::PathBuf, ()> {
    let path_var = std::env::var("PATH").map_err(|_| ())?;
    for dir in std::env::split_paths(&path_var) {
        let candidate = dir.join("uv");
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err(())
}

fn dirs_next_home() -> std::path::PathBuf {
    std::env::var("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::path::PathBuf::from("/root"))
}

// ── Public API ────────────────────────────────────────────────────────────────

/// Start the Python backend.
///
/// # Key design note — MutexGuard and async Send
/// `std::sync::MutexGuard` is `!Send`.  Every lock acquisition lives inside
/// its own `{ … }` block so the guard is provably dropped before any `.await`.
pub async fn start(
    app: tauri::AppHandle,
    state: State<'_, SidecarState>,
) -> Result<String, String> {

    // ── 1. Early-exit checks (guard dropped at end of block) ─────────────────
    {
        let child_lock = state.child.lock().map_err(|e| e.to_string())?;
        if child_lock.is_some() {
            return Ok("already_running".to_string());
        }
    }

    if is_port_in_use(8000) {
        return Ok("port_in_use".to_string());
    }

    // ── 2. Build the command (sync, no await) ─────────────────────────────────
    // CARGO_MANIFEST_DIR is set at compile time to the directory that contains
    // Cargo.toml, i.e. `…/src-tauri/`.  Its parent is the workspace root.
    // This is reliable in all dev environments regardless of how Tauri resolves
    // resource paths at runtime.
    #[cfg(debug_assertions)]
    let backend_dir = {
        let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let workspace_root = manifest_dir
            .parent()
            .ok_or("Cannot determine workspace root from CARGO_MANIFEST_DIR")?;
        workspace_root.join("backend")
    };

    #[cfg(debug_assertions)]
    let cmd = {
        if !backend_dir.exists() {
            return Err(format!(
                "Backend directory not found at: {}",
                backend_dir.display()
            ));
        }

        // Resolve uv — Tauri uses a minimal PATH that may not include ~/.local/bin
        let uv_path = find_uv()
            .ok_or("uv not found. Install uv: https://docs.astral.sh/uv/")?;

        println!("[argus] Using uv at: {}", uv_path.display());

        app.shell()
            .command(uv_path.to_string_lossy().as_ref())
            .args([
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ])
            .current_dir(&backend_dir)
    };

    #[cfg(not(debug_assertions))]
    let cmd = app
        .shell()
        .sidecar("argus-backend")
        .map_err(|e| format!("Sidecar not found: {e}"))?;

    // ── 3. Spawn the process (sync) ───────────────────────────────────────────
    let (mut rx, child) = cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {e}"))?;

    // ── 4. Store the handle (guard dropped before first await) ────────────────
    {
        let mut child_lock = state.child.lock().map_err(|e| e.to_string())?;
        *child_lock = Some(child);
    }

    // ── 5. Log backend output in a background task ────────────────────────────
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    println!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(status) => {
                    eprintln!(
                        "[backend] exited — code: {:?}  signal: {:?}",
                        status.code, status.signal
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    // ── 6. Wait until reachable (first await — no MutexGuard alive) ──────────
    if wait_for_backend(8000, 20).await {
        Ok("started".to_string())
    } else {
        Err("Backend did not become reachable within 20 seconds".to_string())
    }
}

/// Kill the sidecar process.
pub async fn stop(state: State<'_, SidecarState>) -> Result<(), String> {
    let child = {
        let mut lock = state.child.lock().map_err(|e| e.to_string())?;
        lock.take()
    };
    if let Some(c) = child {
        c.kill().map_err(|e| format!("Failed to kill backend: {e}"))?;
        println!("[backend] Process killed");
    }
    Ok(())
}

/// Non-blocking check: do we hold a child process handle?
pub fn is_running(state: &SidecarState) -> bool {
    state
        .child
        .lock()
        .map(|g| g.is_some())
        .unwrap_or(false)
}
