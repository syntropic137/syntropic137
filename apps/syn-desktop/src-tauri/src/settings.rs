//! Desktop settings, persisted with tauri-plugin-store in `settings.json`
//! (in the app config dir).
//!
//! - `apiBaseUrl`: absolute http(s) URL of the Syntropic137 API root, e.g.
//!   `http://localhost:8137/api/v1` (selfhost gateway) or
//!   `http://127.0.0.1:9137` (dev API, no prefix). Unset means the web app keeps its default
//!   (`/api/v1`, which only resolves under the vite dev server proxy).
//! - `globalShortcut`: accelerator for the Command palette. Unset means
//!   `CmdOrCtrl+K`; an empty string disables the global shortcut.

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Wry};
use tauri_plugin_store::StoreExt;
use url::Url;

pub const STORE_FILE: &str = "settings.json";
pub const KEY_API_BASE_URL: &str = "apiBaseUrl";
pub const KEY_GLOBAL_SHORTCUT: &str = "globalShortcut";
pub const DEFAULT_SHORTCUT: &str = "CmdOrCtrl+K";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Settings {
    /// None: use the web app's default base URL.
    pub api_base_url: Option<String>,
    /// Effective accelerator; "" when the global shortcut is disabled.
    pub global_shortcut: String,
}

pub fn load(app: &AppHandle<Wry>) -> Result<Settings, String> {
    let store = app.store(STORE_FILE).map_err(|e| e.to_string())?;
    let api_base_url = store
        .get(KEY_API_BASE_URL)
        .and_then(|v| v.as_str().map(str::to_string))
        .filter(|s| !s.is_empty());
    let global_shortcut = match store.get(KEY_GLOBAL_SHORTCUT) {
        Some(Value::String(s)) => s,
        _ => DEFAULT_SHORTCUT.to_string(),
    };
    Ok(Settings {
        api_base_url,
        global_shortcut,
    })
}

/// Validate and normalise an API base URL: http(s) only, no query or
/// fragment, no trailing slash (the client appends `/executions` etc.).
pub fn normalise_api_base_url(raw: &str) -> Result<String, String> {
    let url = Url::parse(raw.trim()).map_err(|e| format!("not a valid URL: {e}"))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err("the API base URL must start with http:// or https://".into());
    }
    if url.host_str().is_none() {
        return Err("the API base URL needs a host".into());
    }
    if url.query().is_some() || url.fragment().is_some() {
        return Err("the API base URL cannot have a query or fragment".into());
    }
    Ok(url.as_str().trim_end_matches('/').to_string())
}

pub fn save_api_base_url(app: &AppHandle<Wry>, value: Option<&str>) -> Result<(), String> {
    let store = app.store(STORE_FILE).map_err(|e| e.to_string())?;
    match value {
        Some(v) => store.set(KEY_API_BASE_URL, json!(v)),
        None => {
            store.delete(KEY_API_BASE_URL);
        }
    }
    store.save().map_err(|e| e.to_string())
}

pub fn save_global_shortcut(app: &AppHandle<Wry>, value: &str) -> Result<(), String> {
    let store = app.store(STORE_FILE).map_err(|e| e.to_string())?;
    store.set(KEY_GLOBAL_SHORTCUT, json!(value));
    store.save().map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::normalise_api_base_url as n;

    #[test]
    fn normalises() {
        assert_eq!(
            n("http://127.0.0.1:9137/").unwrap(),
            "http://127.0.0.1:9137"
        );
        assert_eq!(
            n(" https://syn.example.com/api/v1/ ").unwrap(),
            "https://syn.example.com/api/v1"
        );
    }

    #[test]
    fn rejects() {
        assert!(n("ftp://x").is_err());
        assert!(n("javascript:alert(1)").is_err());
        assert!(n("/api/v1").is_err());
        assert!(n("http://x/?a=1").is_err());
    }
}
