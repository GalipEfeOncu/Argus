use serde::Serialize;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const READY_TIMEOUT: Duration = Duration::from_secs(20);
const GRACEFUL_STOP_TIMEOUT: Duration = Duration::from_secs(3);
const MAX_QUICK_CRASH_RESTARTS: u8 = 3;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendConnection {
    pub base_url: String,
    pub websocket_url: String,
    pub access_token: String,
    pub version: String,
}

struct ManagedProcess {
    child: CommandChild,
    generation: u64,
    port: u16,
    started_at: Instant,
}

#[derive(Default)]
struct Lifecycle {
    process: Option<ManagedProcess>,
    connection: Option<BackendConnection>,
    starting: bool,
    generation: u64,
    quick_crashes: u8,
}

impl Lifecycle {
    fn owns_generation(&self, generation: u64) -> bool {
        self.generation == generation
    }

    fn owns_process(&self, generation: u64) -> bool {
        self.owns_generation(generation)
            && self
                .process
                .as_ref()
                .is_some_and(|process| process.generation == generation)
    }

    fn has_activity(&self) -> bool {
        self.starting || self.process.is_some()
    }

    fn record_crash(&mut self, quick_crash: bool) -> bool {
        self.quick_crashes = if quick_crash {
            self.quick_crashes.saturating_add(1)
        } else {
            1
        };
        self.quick_crashes <= MAX_QUICK_CRASH_RESTARTS
    }
}

pub struct SidecarState {
    lifecycle: Mutex<Lifecycle>,
    bridge_token: String,
}

impl Default for SidecarState {
    fn default() -> Self {
        Self {
            lifecycle: Mutex::new(Lifecycle::default()),
            bridge_token: uuid::Uuid::new_v4().to_string(),
        }
    }
}

pub fn bridge_token(state: &SidecarState) -> &str {
    &state.bridge_token
}

fn allocate_loopback_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))
        .map_err(|_| "A private backend port could not be allocated".to_string())?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|_| "The private backend port could not be inspected".to_string())
}

#[cfg(debug_assertions)]
fn find_uv() -> Option<std::path::PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|directory| directory.join(if cfg!(windows) { "uv.exe" } else { "uv" }))
        .find(|candidate| candidate.is_file())
}

fn authorization(token: &str) -> String {
    format!("Bearer {token}")
}

async fn wait_for_backend(connection: &BackendConnection) -> bool {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
    {
        Ok(client) => client,
        Err(_) => return false,
    };
    let deadline = Instant::now() + READY_TIMEOUT;
    while Instant::now() < deadline {
        let response = client
            .get(format!("{}/health", connection.base_url))
            .header(
                reqwest::header::AUTHORIZATION,
                authorization(&connection.access_token),
            )
            .send()
            .await;
        if let Ok(response) = response {
            let ready = response.status().is_success()
                && response
                    .json::<serde_json::Value>()
                    .await
                    .ok()
                    .and_then(|value| {
                        value
                            .get("version")
                            .and_then(serde_json::Value::as_str)
                            .map(str::to_owned)
                    })
                    .is_some_and(|version| version == connection.version);
            if ready {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
    false
}

pub async fn start(
    app: tauri::AppHandle,
    state: State<'_, SidecarState>,
) -> Result<BackendConnection, String> {
    start_owned(app, &state).await
}

async fn start_owned(
    app: tauri::AppHandle,
    state: &SidecarState,
) -> Result<BackendConnection, String> {
    let mut owns_start = false;
    let mut generation = None;
    for _ in 0..500 {
        let should_wait = {
            let mut lifecycle = state
                .lifecycle
                .lock()
                .map_err(|_| "Backend lifecycle is unavailable")?;
            if let Some(connection) = lifecycle.connection.clone() {
                return Ok(connection);
            }
            if lifecycle.starting {
                true
            } else {
                lifecycle.generation += 1;
                lifecycle.starting = true;
                owns_start = true;
                generation = Some(lifecycle.generation);
                false
            }
        };
        if !should_wait {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    if !owns_start {
        return Err("The backend start operation timed out".to_string());
    }
    let generation = generation.ok_or("The backend start generation is unavailable")?;
    let result = launch_owned(app, state, generation).await;
    if result.is_err() {
        if let Ok(mut lifecycle) = state.lifecycle.lock() {
            if lifecycle.owns_generation(generation) {
                lifecycle.starting = false;
            }
        }
    }
    result
}

async fn launch_owned(
    app: tauri::AppHandle,
    state: &SidecarState,
    generation: u64,
) -> Result<BackendConnection, String> {
    let port = allocate_loopback_port()?;
    let access_token = uuid::Uuid::new_v4().to_string();
    let version = env!("CARGO_PKG_VERSION").to_string();
    let connection = BackendConnection {
        base_url: format!("http://127.0.0.1:{port}"),
        websocket_url: format!("ws://127.0.0.1:{port}"),
        access_token,
        version,
    };

    #[cfg(debug_assertions)]
    let mut command = {
        let backend_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .ok_or("The workspace root could not be resolved")?
            .join("backend");
        let uv = find_uv().ok_or("uv was not found on PATH")?;
        app.shell()
            .command(uv.to_string_lossy().as_ref())
            .args(["run", "python", "sidecar_main.py"])
            .current_dir(backend_dir)
    };

    #[cfg(not(debug_assertions))]
    let mut command = app
        .shell()
        .sidecar("argus-backend")
        .map_err(|_| "The version-matched backend sidecar is unavailable".to_string())?;

    command = command
        .env("ARGUS_HOST", "127.0.0.1")
        .env("ARGUS_PORT", port.to_string())
        .env("ARGUS_ACCESS_TOKEN", &connection.access_token)
        .env("ARGUS_NATIVE_BRIDGE_TOKEN", bridge_token(state))
        .env("ARGUS_DEBUG", "false")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("PYTHONUNBUFFERED", "1");

    let (mut events, child) = match command.spawn() {
        Ok(spawned) => spawned,
        Err(_) => {
            let mut lifecycle = state
                .lifecycle
                .lock()
                .map_err(|_| "Backend lifecycle is unavailable")?;
            if lifecycle.owns_generation(generation) {
                lifecycle.starting = false;
            }
            return Err("The backend sidecar could not be started".to_string());
        }
    };
    {
        let mut lifecycle = state
            .lifecycle
            .lock()
            .map_err(|_| "Backend lifecycle is unavailable")?;
        if !lifecycle.owns_generation(generation) || !lifecycle.starting {
            let _ = child.kill();
            return Err("The backend start was superseded".to_string());
        }
        lifecycle.process = Some(ManagedProcess {
            child,
            generation,
            port,
            started_at: Instant::now(),
        });
    }

    let monitor_app = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut diagnostic_notice_emitted = false;
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Terminated(_) => {
                    handle_termination(&monitor_app, generation);
                    break;
                }
                CommandEvent::Stderr(line) if !line.is_empty() && !diagnostic_notice_emitted => {
                    diagnostic_notice_emitted = true;
                    eprintln!("[argus-sidecar] diagnostic output suppressed");
                }
                _ => {}
            }
        }
    });

    if !wait_for_backend(&connection).await {
        let process = {
            let mut lifecycle = state
                .lifecycle
                .lock()
                .map_err(|_| "Backend lifecycle is unavailable")?;
            if lifecycle.owns_process(generation) {
                lifecycle.starting = false;
                lifecycle.process.take()
            } else {
                None
            }
        };
        if let Some(process) = process {
            let _ = process.child.kill();
        }
        return Err("The backend did not pass its authenticated readiness check".to_string());
    }
    {
        let mut lifecycle = state
            .lifecycle
            .lock()
            .map_err(|_| "Backend lifecycle is unavailable")?;
        if !lifecycle.owns_process(generation) {
            return Err("The backend exited before readiness was published".to_string());
        }
        lifecycle.connection = Some(connection.clone());
        lifecycle.starting = false;
    }
    Ok(connection)
}

fn handle_termination(app: &tauri::AppHandle, generation: u64) {
    let should_restart = {
        let state = app.state::<SidecarState>();
        let mut lifecycle = match state.lifecycle.lock() {
            Ok(lifecycle) => lifecycle,
            Err(_) => return,
        };
        let Some(process) = lifecycle.process.as_ref() else {
            return;
        };
        if process.generation != generation {
            return;
        }
        let quick_crash = process.started_at.elapsed() < Duration::from_secs(60);
        lifecycle.process = None;
        lifecycle.connection = None;
        lifecycle.starting = false;
        lifecycle.record_crash(quick_crash)
    };
    if should_restart {
        let _ = app.emit("argus://sidecar-crashed", generation);
    } else {
        let _ = app.emit("argus://sidecar-crash-exhausted", generation);
    }
}

pub async fn stop(state: State<'_, SidecarState>) -> Result<(), String> {
    stop_owned(&state).await
}

async fn stop_owned(state: &SidecarState) -> Result<(), String> {
    let (process, connection) = {
        let mut lifecycle = state
            .lifecycle
            .lock()
            .map_err(|_| "Backend lifecycle is unavailable")?;
        lifecycle.starting = false;
        lifecycle.quick_crashes = 0;
        (lifecycle.process.take(), lifecycle.connection.take())
    };
    let Some(process) = process else {
        return Ok(());
    };
    if let Some(connection) = connection {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(1))
            .build();
        if let Ok(client) = client {
            let _ = client
                .post(format!("{}/runtime/shutdown", connection.base_url))
                .header(
                    reqwest::header::AUTHORIZATION,
                    authorization(&connection.access_token),
                )
                .send()
                .await;
            let deadline = Instant::now() + GRACEFUL_STOP_TIMEOUT;
            while Instant::now() < deadline {
                if std::net::TcpStream::connect((std::net::Ipv4Addr::LOCALHOST, process.port))
                    .is_err()
                {
                    return Ok(());
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
    }
    terminate_descendants(process.child.pid());
    process
        .child
        .kill()
        .map_err(|_| "The backend process tree could not be stopped".to_string())
}

fn terminate_descendants(root_pid: u32) {
    use sysinfo::{Pid, ProcessesToUpdate, Signal, System};

    let root = Pid::from_u32(root_pid);
    let mut system = System::new();
    system.refresh_processes(ProcessesToUpdate::All, true);
    let mut descendants = Vec::new();
    let mut frontier = vec![root];
    while let Some(parent) = frontier.pop() {
        for (pid, process) in system.processes() {
            if process.parent() == Some(parent) && !descendants.contains(pid) {
                descendants.push(*pid);
                frontier.push(*pid);
            }
        }
    }
    for pid in descendants.into_iter().rev() {
        if let Some(process) = system.process(pid) {
            let _ = process
                .kill_with(Signal::Kill)
                .or_else(|| Some(process.kill()));
        }
    }
}

pub fn connection(state: &SidecarState) -> Option<BackendConnection> {
    state.lifecycle.lock().ok()?.connection.clone()
}

pub fn is_running(state: &SidecarState) -> bool {
    state
        .lifecycle
        .lock()
        .map(|lifecycle| lifecycle.process.is_some())
        .unwrap_or(false)
}

pub fn has_lifecycle_activity(state: &SidecarState) -> bool {
    state
        .lifecycle
        .lock()
        .map(|lifecycle| lifecycle.has_activity())
        .unwrap_or(true)
}

pub async fn can_idle_shutdown(state: &SidecarState) -> bool {
    let Some(connection) = connection(state) else {
        return false;
    };
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(client) => client,
        Err(_) => return false,
    };
    match client
        .get(format!("{}/runtime/idle", connection.base_url))
        .header(
            reqwest::header::AUTHORIZATION,
            authorization(&connection.access_token),
        )
        .send()
        .await
    {
        Ok(response) if response.status().is_success() => response
            .json::<serde_json::Value>()
            .await
            .ok()
            .and_then(|value| value.get("idle").and_then(serde_json::Value::as_bool))
            .unwrap_or(false),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allocated_ports_are_dynamic_loopback_ports() {
        let first = allocate_loopback_port().expect("first port");
        let second = allocate_loopback_port().expect("second port");
        assert_ne!(first, 0);
        assert_ne!(second, 0);
        assert_ne!(first, second);
    }

    #[test]
    fn connection_serialization_does_not_expose_bridge_token() {
        let value = serde_json::to_value(BackendConnection {
            base_url: "http://127.0.0.1:12345".into(),
            websocket_url: "ws://127.0.0.1:12345".into(),
            access_token: "session-token".into(),
            version: "0.1.0".into(),
        })
        .expect("serialize");
        assert_eq!(value["accessToken"], "session-token");
        assert!(value.get("bridgeToken").is_none());
    }

    #[test]
    fn lifecycle_generation_rejects_stale_start_and_exit_sees_starting_work() {
        let mut lifecycle = Lifecycle {
            generation: 4,
            starting: true,
            ..Lifecycle::default()
        };
        assert!(lifecycle.has_activity());
        assert!(lifecycle.owns_generation(4));
        lifecycle.generation = 5;
        assert!(!lifecycle.owns_generation(4));
        lifecycle.starting = false;
        assert!(!lifecycle.has_activity());
    }

    #[test]
    fn crash_budget_restarts_three_times_then_exposes_exhaustion() {
        let mut lifecycle = Lifecycle::default();
        assert!(lifecycle.record_crash(true));
        assert!(lifecycle.record_crash(true));
        assert!(lifecycle.record_crash(true));
        assert!(!lifecycle.record_crash(true));
    }
}
