//! Native menu bar. Custom items emit events the web app listens to through
//! apps/syn-desktop/bridge; predefined items (copy, paste, quit...) are native.

use tauri::menu::{Menu, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
use tauri::{AppHandle, Wry};

pub const ID_SETTINGS: &str = "menu.settings";
pub const ID_PALETTE: &str = "menu.palette";
pub const ID_RELOAD: &str = "menu.reload";
pub const GO_PREFIX: &str = "menu.go:";

/// The eight sections, in capsule order (apps/syn-ui/src/shell/nav.ts).
pub const SECTIONS: [(&str, &str); 8] = [
    ("Overview", "/"),
    ("Workflows", "/workflows"),
    ("Executions", "/executions"),
    ("Evals", "/evals"),
    ("Sessions", "/sessions"),
    ("Artifacts", "/artifacts"),
    ("Triggers", "/triggers"),
    ("Repos", "/repos"),
];

pub fn build(app: &AppHandle<Wry>) -> tauri::Result<Menu<Wry>> {
    let settings = MenuItemBuilder::with_id(ID_SETTINGS, "Settings…")
        .accelerator("CmdOrCtrl+,")
        .build(app)?;

    #[cfg(target_os = "macos")]
    let first = SubmenuBuilder::new(app, "Syntropic137")
        .about(None)
        .separator()
        .item(&settings)
        .separator()
        .services()
        .separator()
        .hide()
        .hide_others()
        .show_all()
        .separator()
        .quit()
        .build()?;
    #[cfg(not(target_os = "macos"))]
    let first = SubmenuBuilder::new(app, "File")
        .item(&settings)
        .separator()
        .quit()
        .build()?;

    // Without an Edit menu, copy/paste shortcuts do nothing in a macOS webview.
    let edit = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;

    // The palette accelerator only shows the hint and covers the case where
    // the global shortcut is disabled or failed to register; state.rs debounces.
    let view = SubmenuBuilder::new(app, "View")
        .item(
            &MenuItemBuilder::with_id(ID_PALETTE, "Command Palette…")
                .accelerator("CmdOrCtrl+K")
                .build(app)?,
        )
        .separator()
        .item(
            &MenuItemBuilder::with_id(ID_RELOAD, "Reload")
                .accelerator("CmdOrCtrl+R")
                .build(app)?,
        )
        .item(&PredefinedMenuItem::fullscreen(app, None)?)
        .build()?;

    let mut go = SubmenuBuilder::new(app, "Go");
    for (i, (label, path)) in SECTIONS.iter().enumerate() {
        go = go.item(
            &MenuItemBuilder::with_id(format!("{GO_PREFIX}{path}"), *label)
                .accelerator(format!("CmdOrCtrl+{}", i + 1))
                .build(app)?,
        );
    }
    let go = go.build()?;

    let window = SubmenuBuilder::new(app, "Window")
        .minimize()
        .maximize()
        .separator()
        .close_window()
        .build()?;

    MenuBuilder::new(app)
        .items(&[&first, &edit, &view, &go, &window])
        .build()
}
