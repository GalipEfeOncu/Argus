use crate::sidecar::SidecarState;
use tauri::State;

/// Start the Python FastAPI backend as a sidecar process.
///
/// Returns one of: "started" | "already_running" | "port_in_use" | Err(msg)
#[tauri::command]
pub async fn start_backend(
    app: tauri::AppHandle,
    state: State<'_, SidecarState>,
) -> Result<String, String> {
    crate::sidecar::start(app, state).await
}

/// Stop the Python FastAPI backend sidecar.
#[tauri::command]
pub async fn stop_backend(state: State<'_, SidecarState>) -> Result<(), String> {
    crate::sidecar::stop(state).await
}

/// Check if the backend process is running (we hold the handle).
///
/// Note: this reflects whether *we* spawned and own the process — not
/// whether the HTTP server is actually reachable.  Use the frontend
/// health-poll for the latter.
#[tauri::command]
pub async fn get_backend_status(state: State<'_, SidecarState>) -> Result<bool, String> {
    Ok(crate::sidecar::is_running(&state))
}

/// Open a native folder-picker dialog and return the selected path string.
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

const CREDENTIAL_SERVICE: &str = "com.argus.app.provider";

fn credential_entry(reference: &str) -> Result<keyring::Entry, String> {
    if !reference.starts_with("argus-provider-") || reference.len() > 256 {
        return Err("Invalid credential reference".to_string());
    }
    keyring::Entry::new(CREDENTIAL_SERVICE, reference).map_err(|_| "Credential store is unavailable".to_string())
}

/// Probe whether the native credential-service backend can create an entry.
/// This never reads, writes, or exposes a provider credential.
#[tauri::command]
pub async fn credential_store_available() -> bool {
    credential_entry("argus-provider-health-check").is_ok()
}

/// Store a provider secret in the platform credential service. The secret is
/// intentionally not returned to JavaScript or persisted by the application.
#[tauri::command]
pub async fn store_provider_credential(credential: String) -> Result<String, String> {
    if credential.trim().is_empty() || credential.len() > 16_000 {
        return Err("Credential must not be empty".to_string());
    }
    let reference = format!("argus-provider-{}", uuid::Uuid::new_v4());
    credential_entry(&reference)?.set_password(&credential).map_err(|_| "Credential could not be saved".to_string())?;
    Ok(reference)
}

async fn native_credential_reference(profile_id: &str, state: &SidecarState) -> Result<Option<String>, String> {
    if !profile_id.starts_with("prv_") || profile_id.len() > 160 { return Err("Invalid provider profile".to_string()); }
    let response = reqwest::Client::builder().timeout(std::time::Duration::from_secs(5)).build()
        .map_err(|_| "Credential store is unavailable".to_string())?
        .get(format!("http://127.0.0.1:8000/providers/{profile_id}/credential-reference"))
        .header("X-Argus-Bridge-Token", crate::sidecar::bridge_token(state))
        .send().await.map_err(|_| "Credential store is unavailable".to_string())?;
    if !response.status().is_success() { return Err("Credential lookup was rejected".to_string()); }
    Ok(response.json::<CredentialReferenceResponse>().await.map_err(|_| "Credential lookup was invalid".to_string())?.credential_reference)
}

/// Resolve a key only inside the native process and hand it to its authenticated
/// local sidecar as a short-lived lease. It never crosses the webview boundary.
#[tauri::command]
pub async fn refresh_provider_credential(
    profile_id: String,
    state: State<'_, SidecarState>,
) -> Result<(), String> {
    let credential_reference = native_credential_reference(&profile_id, &state).await?
        .ok_or("Provider does not have a credential reference")?;
    let credential = credential_entry(&credential_reference)?.get_password().map_err(|_| "Credential is unavailable".to_string())?;
    let response = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build().map_err(|_| "Credential handoff is unavailable".to_string())?
        .put(format!("http://127.0.0.1:8000/providers/{profile_id}/credential"))
        .header("X-Argus-Bridge-Token", crate::sidecar::bridge_token(&state))
        .json(&serde_json::json!({ "credential": credential, "credentialReference": credential_reference }))
        .send().await.map_err(|_| "Credential handoff is unavailable".to_string())?;
    if !response.status().is_success() {
        return Err("Credential handoff was rejected".to_string());
    }
    Ok(())
}

#[tauri::command]
pub async fn delete_provider_credential(credential_reference: String) -> Result<(), String> {
    credential_entry(&credential_reference)?.delete_credential().map_err(|_| "Credential could not be removed".to_string())
}

#[derive(serde::Deserialize)]
struct CredentialReferenceResponse { #[serde(rename = "credentialReference")] credential_reference: Option<String> }

/// Look up an opaque reference through the authenticated native bridge, then
/// delete it from the OS store without revealing that reference to the webview.
#[tauri::command]
pub async fn remove_provider_credential(profile_id: String, state: State<'_, SidecarState>) -> Result<(), String> {
    if let Some(reference) = native_credential_reference(&profile_id, &state).await? { delete_provider_credential(reference).await?; }
    Ok(())
}
