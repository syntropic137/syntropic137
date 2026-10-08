//! Tray icon with a Live-state dot. The web app reports its live connection
//! state (skyline-core `LiveState`) through the `set_live_state` command.

use std::str::FromStr;

use serde::{Deserialize, Serialize};
use tauri::image::Image;
use tauri::menu::{MenuBuilder, MenuItem, MenuItemBuilder, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, Wry};

use crate::state::AppState;

pub const TRAY_ID: &str = "syn-tray";
pub const MENU_SHOW: &str = "tray.show";
pub const MENU_PALETTE: &str = "tray.palette";
pub const MENU_STATUS: &str = "tray.status";

const BASE_ICON: &[u8] = include_bytes!("../icons/32x32.png");

/// Mirrors `LiveState` in packages/syn-ui/skyline-core/src/patterns/types.ts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum LiveState {
    Live,
    #[default]
    Connecting,
    Offline,
    Fixtures,
}

impl FromStr for LiveState {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "live" => Ok(Self::Live),
            "connecting" => Ok(Self::Connecting),
            "offline" => Ok(Self::Offline),
            "fixtures" => Ok(Self::Fixtures),
            other => Err(format!(
                "unknown live state {other:?} (expected live | connecting | offline | fixtures)"
            )),
        }
    }
}

impl LiveState {
    pub fn label(self) -> &'static str {
        match self {
            Self::Live => "Live",
            Self::Connecting => "Connecting",
            Self::Offline => "Offline",
            Self::Fixtures => "Fixtures",
        }
    }

    /// Dot colour (RGB). The tray is native chrome, outside the CSS token system.
    fn rgb(self) -> [u8; 3] {
        match self {
            Self::Live => [46, 213, 115],
            Self::Connecting => [245, 184, 46],
            Self::Offline => [240, 82, 82],
            Self::Fixtures => [110, 160, 255],
        }
    }
}

/// The base app icon with a status dot in the bottom-right corner.
pub fn icon_for(state: LiveState) -> tauri::Result<Image<'static>> {
    let base = Image::from_bytes(BASE_ICON)?;
    let (w, h) = (base.width(), base.height());
    let mut rgba = base.rgba().to_vec();
    let r = (w.min(h) as f32) * 0.22; // dot radius
    let ring = (w.min(h) as f32) * 0.07; // dark outline so the dot reads on any tray
    let cx = w as f32 - r - ring - 0.5;
    let cy = h as f32 - r - ring - 0.5;
    let [dr, dg, db] = state.rgb();
    for y in 0..h {
        for x in 0..w {
            let dx = x as f32 + 0.5 - cx;
            let dy = y as f32 + 0.5 - cy;
            let d = (dx * dx + dy * dy).sqrt();
            let i = ((y * w + x) * 4) as usize;
            if d <= r {
                rgba[i..i + 4].copy_from_slice(&[dr, dg, db, 255]);
            } else if d <= r + ring {
                rgba[i..i + 4].copy_from_slice(&[11, 15, 20, 255]);
            }
        }
    }
    Ok(Image::new_owned(rgba, w, h))
}

fn tooltip(state: LiveState) -> String {
    format!("Syntropic137 · {}", state.label())
}

fn status_text(state: LiveState) -> String {
    format!("Status: {}", state.label())
}

pub fn build(app: &AppHandle<Wry>) -> tauri::Result<()> {
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

    if let Ok(mut slot) = app.state::<AppState>().tray_status.lock() {
        *slot = Some(status);
    }
    Ok(())
}

pub fn set_state(app: &AppHandle<Wry>, state: LiveState) -> tauri::Result<()> {
    let st = app.state::<AppState>();
    {
        let mut cur = st.live.lock().expect("live state lock");
        if *cur == state {
            return Ok(());
        }
        *cur = state;
    }
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        tray.set_icon(Some(icon_for(state)?))?;
        tray.set_tooltip(Some(tooltip(state)))?;
    }
    if let Some(item) = st.tray_status.lock().expect("tray status lock").as_ref() {
        item.set_text(status_text(state))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_core_live_states() {
        for s in ["live", "connecting", "offline", "fixtures"] {
            assert!(s.parse::<LiveState>().is_ok(), "{s}");
        }
        assert!("reconnecting".parse::<LiveState>().is_err());
    }

    #[test]
    fn dot_is_drawn() {
        let img = icon_for(LiveState::Live).unwrap();
        let (w, h) = (img.width(), img.height());
        // a pixel inside the dot, near the bottom-right corner
        let x = w - (w as f32 * 0.29) as u32;
        let y = h - (h as f32 * 0.29) as u32;
        let i = ((y * w + x) * 4) as usize;
        assert_eq!(&img.rgba()[i..i + 4], &[46, 213, 115, 255]);
    }
}
