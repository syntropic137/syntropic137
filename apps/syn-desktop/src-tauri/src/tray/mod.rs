//! Tray icon with a Live-state dot. The web app reports its live connection
//! state (skyline-core `LiveState`) through the `set_live_state` command.
//!
//! The tray owns no app state: callers pass the slots it reads and writes, so
//! `state` depends on `tray` (for `LiveState`) and never the other way round.

mod icon;
mod live_state;

use std::sync::Mutex;

use tauri::menu::{MenuBuilder, MenuItem, MenuItemBuilder, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Wry};

pub use icon::icon_for;
pub use live_state::LiveState;

pub const TRAY_ID: &str = "syn-tray";
pub const MENU_SHOW: &str = "tray.show";
pub const MENU_PALETTE: &str = "tray.palette";
pub const MENU_STATUS: &str = "tray.status";

/// The tray's disabled "Status: ..." menu item, kept so `set_state` can relabel it.
pub type StatusSlot = Mutex<Option<MenuItem<Wry>>>;

fn tooltip(state: LiveState) -> String {
    format!("Syntropic137 · {}", state.label())
}

fn status_text(state: LiveState) -> String {
    format!("Status: {}", state.label())
}

pub fn build(app: &AppHandle<Wry>, status_slot: &StatusSlot) -> tauri::Result<()> {
    let state = LiveState::default();
    let status: MenuItem<Wry> = MenuItemBuilder::with_id(MENU_STATUS, status_text(state))
        .enabled(false)
        .build(app)?;
    let menu = MenuBuilder::new(app)
        .item(&status)
        .item(&PredefinedMenuItem::separator(app)?)
        .item(&MenuItemBuilder::with_id(MENU_SHOW, "Show Syntropic137").build(app)?)
        .item(&MenuItemBuilder::with_id(MENU_PALETTE, "Command Palette…").build(app)?)
        .item(&PredefinedMenuItem::separator(app)?)
        .item(&PredefinedMenuItem::quit(app, Some("Quit Syntropic137"))?)
        .build()?;

    TrayIconBuilder::with_id(TRAY_ID)
        .icon(icon_for(state)?)
        .tooltip(tooltip(state))
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            // Left click shows the window (Windows/macOS; Linux trays only open the menu).
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                crate::show_main(tray.app_handle());
            }
        })
        .build(app)?;

    if let Ok(mut slot) = status_slot.lock() {
        *slot = Some(status);
    }
    Ok(())
}

pub fn set_state(
    app: &AppHandle<Wry>,
    live: &Mutex<LiveState>,
    status_slot: &StatusSlot,
    state: LiveState,
) -> tauri::Result<()> {
    {
        let mut cur = live.lock().expect("live state lock");
        if *cur == state {
            return Ok(());
        }
        *cur = state;
    }
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        tray.set_icon(Some(icon_for(state)?))?;
        tray.set_tooltip(Some(tooltip(state)))?;
    }
    if let Some(item) = status_slot.lock().expect("tray status lock").as_ref() {
        item.set_text(status_text(state))?;
    }
    Ok(())
}
