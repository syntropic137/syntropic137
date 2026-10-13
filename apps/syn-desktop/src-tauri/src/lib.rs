//! Syntropic137 desktop shell (Skyline spec, Platforms: Desktop app, phase 5).
//!
//! A Tauri 2 window around the apps/syn-ui build. The shell adds what a
//! browser tab cannot: a native menu bar, a global Cmd/Ctrl+K for the Command
//! palette, a tray icon whose dot shows the Live state, syn137:// deep links
//! into executions, and a persisted API base URL. The web app talks to it
//! through apps/syn-desktop/bridge (events + the commands below).
//!
//! Events emitted to the `main` window (names shared with bridge/index.ts):
//!   syn://command-palette   ()                 open the Command palette
//!   syn://navigate          { path: string }   go to an app route
//!   syn://open-settings     ()                 show desktop settings
//!   syn://settings-changed  Settings           settings were saved

mod deeplink;
mod menu;
mod settings;
mod state;
mod tray;

use std::sync::atomic::Ordering;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::webview::PageLoadEvent;
use tauri::{AppHandle, Emitter, Manager, WindowEvent, Wry};

use settings::Settings;
use state::AppState;
use tray::LiveState;

pub const MAIN: &str = "main";
pub const EV_PALETTE: &str = "syn://command-palette";
pub const EV_NAVIGATE: &str = "syn://navigate";
pub const EV_OPEN_SETTINGS: &str = "syn://open-settings";
pub const EV_SETTINGS_CHANGED: &str = "syn://settings-changed";

#[derive(Clone, Serialize)]
struct NavigatePayload {
    path: String,
}

pub(crate) fn show_main(app: &AppHandle<Wry>) {
    if let Some(w) = app.get_webview_window(MAIN) {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn open_palette(app: &AppHandle<Wry>) {
    let st = app.state::<AppState>();
    {
        let mut last = st.last_palette.lock().expect("palette lock");
        let now = Instant::now();
        if last.is_some_and(|t| now.duration_since(t) < Duration::from_millis(250)) {
            return;
        }
        *last = Some(now);
    }
    show_main(app);
    let _ = app.emit_to(MAIN, EV_PALETTE, ());
}

/// Send the page to a route, or park it until the page calls `desktop_ready`.
fn navigate(app: &AppHandle<Wry>, path: String) {
    show_main(app);
    let st = app.state::<AppState>();
    if st.ready.load(Ordering::SeqCst) {
        let _ = app.emit_to(MAIN, EV_NAVIGATE, NavigatePayload { path });
    } else {
        *st.pending_route.lock().expect("pending route lock") = Some(path);
    }
}

fn handle_deep_links<I: IntoIterator<Item = String>>(app: &AppHandle<Wry>, urls: I) {
    // Several URLs in one launch: the last one wins.
    if let Some(route) = urls
        .into_iter()
        .filter_map(|u| deeplink::route_for(&u))
        .last()
    {
        navigate(app, route);
    }
}

#[cfg(desktop)]
fn apply_global_shortcut(app: &AppHandle<Wry>, accelerator: &str) -> Result<(), String> {
    use tauri_plugin_global_shortcut::GlobalShortcutExt;
    let gs = app.global_shortcut();
    let st = app.state::<AppState>();
    let mut cur = st.shortcut.lock().expect("shortcut lock");
    if let Some(old) = cur.take() {
        let _ = gs.unregister(old.as_str());
    }
    if accelerator.is_empty() {
        return Ok(());
    }
    gs.register(accelerator)
        .map_err(|e| format!("could not register global shortcut {accelerator:?}: {e}"))?;
    *cur = Some(accelerator.to_string());
    Ok(())
}

#[cfg(not(desktop))]
fn apply_global_shortcut(_app: &AppHandle<Wry>, _accelerator: &str) -> Result<(), String> {
    Ok(())
}

// ---------------------------------------------------------------- commands

/// The page is listening. Returns a route that arrived before it was (a cold
/// start deep link), at most once.
#[tauri::command]
fn desktop_ready(state: tauri::State<'_, AppState>) -> Option<String> {
    state.ready.store(true, Ordering::SeqCst);
    state.pending_route.lock().ok().and_then(|mut p| p.take())
}

/// Live state for the tray dot: "live" | "connecting" | "offline" | "fixtures".
#[tauri::command]
fn set_live_state(app: AppHandle<Wry>, state: String) -> Result<(), String> {
    let parsed: LiveState = state.parse()?;
    let st = app.state::<AppState>();
    tray::set_state(&app, &st.live, &st.tray_status, parsed).map_err(|e| e.to_string())
}

#[tauri::command]
fn get_settings(app: AppHandle<Wry>) -> Result<Settings, String> {
    settings::load(&app)
}

/// Set (or with null / "" clear) the API base URL. Returns the saved settings.
#[tauri::command]
fn set_api_base_url(app: AppHandle<Wry>, url: Option<String>) -> Result<Settings, String> {
    let value = match url.as_deref().map(str::trim) {
        None | Some("") => None,
        Some(raw) => Some(settings::normalise_api_base_url(raw)?),
    };
    settings::save_api_base_url(&app, value.as_deref())?;
    let saved = settings::load(&app)?;
    let _ = app.emit_to(MAIN, EV_SETTINGS_CHANGED, saved.clone());
    Ok(saved)
}

/// Change the global Command palette shortcut ("" disables it). On failure
/// the previous shortcut is restored and nothing is saved.
#[tauri::command]
fn set_global_shortcut(app: AppHandle<Wry>, shortcut: String) -> Result<Settings, String> {
    let previous = settings::load(&app)?.global_shortcut;
    let next = shortcut.trim().to_string();
    if let Err(e) = apply_global_shortcut(&app, &next) {
        let _ = apply_global_shortcut(&app, &previous);
        return Err(e);
    }
    settings::save_global_shortcut(&app, &next)?;
    let saved = settings::load(&app)?;
    let _ = app.emit_to(MAIN, EV_SETTINGS_CHANGED, saved.clone());
    Ok(saved)
}

// ---------------------------------------------------------------- app

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::<Wry>::default();

    // Single instance must be the first plugin. On Windows/Linux a second
    // launch (for example a clicked syn137:// link) is forwarded here, and
    // its deep-link feature re-emits the URL through on_open_url.
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            show_main(app);
        }));
        builder = builder.plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                        open_palette(app);
                    }
                })
                .build(),
        );
    }

    builder
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_deep_link::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            desktop_ready,
            set_live_state,
            get_settings,
            set_api_base_url,
            set_global_shortcut
        ])
        .on_page_load(|webview, payload| {
            // A reload drops the page's listeners: park routes until it is ready again.
            if payload.event() == PageLoadEvent::Started {
                webview
                    .state::<AppState>()
                    .ready
                    .store(false, Ordering::SeqCst);
            }
        })
        .on_menu_event(|app, event| {
            let id = event.id().as_ref();
            match id {
                menu::ID_SETTINGS => {
                    show_main(app);
                    let _ = app.emit_to(MAIN, EV_OPEN_SETTINGS, ());
                }
                menu::ID_PALETTE | tray::MENU_PALETTE => open_palette(app),
                menu::ID_RELOAD => {
                    if let Some(w) = app.get_webview_window(MAIN) {
                        let _ = w.eval("window.location.reload()");
                    }
                }
                tray::MENU_SHOW => show_main(app),
                _ => {
                    if let Some(path) = id.strip_prefix(menu::GO_PREFIX) {
                        navigate(app, path.to_string());
                    }
                }
            }
        })
        .on_window_event(|window, event| {
            // Closing the window keeps the app (and its tray dot) running.
            // Quit from the menu, the tray, or Cmd+Q.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == MAIN {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            let handle = app.handle().clone();

            app.set_menu(menu::build(&handle)?)?;
            tray::build(&handle, &handle.state::<AppState>().tray_status)?;

            #[cfg(desktop)]
            {
                let accel = settings::load(&handle)
                    .map(|s| s.global_shortcut)
                    .unwrap_or_else(|_| settings::DEFAULT_SHORTCUT.to_string());
                if let Err(e) = apply_global_shortcut(&handle, &accel) {
                    // Wayland and some desktops refuse global shortcuts; the
                    // View menu accelerator still works while focused.
                    eprintln!("[syn-desktop] {e}");
                }
            }

            {
                use tauri_plugin_deep_link::DeepLinkExt;
                // Dev builds and AppImages are not registered by an installer.
                #[cfg(all(debug_assertions, any(windows, target_os = "linux")))]
                if let Err(e) = app.deep_link().register_all() {
                    eprintln!("[syn-desktop] deep link registration failed: {e}");
                }
                let h = handle.clone();
                app.deep_link().on_open_url(move |event| {
                    handle_deep_links(&h, event.urls().into_iter().map(|u| u.to_string()));
                });
                if let Ok(Some(urls)) = app.deep_link().get_current() {
                    handle_deep_links(&handle, urls.into_iter().map(|u| u.to_string()));
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Syntropic137 desktop app")
        .run(|_app, _event| {
            // macOS: clicking the dock icon brings the hidden window back.
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = _event {
                show_main(_app);
            }
        });
}
