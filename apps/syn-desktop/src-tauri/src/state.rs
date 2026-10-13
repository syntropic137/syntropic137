use std::sync::atomic::AtomicBool;
use std::sync::Mutex;
use std::time::Instant;

use crate::tray::{LiveState, StatusSlot};

#[derive(Default)]
pub struct AppState {
    /// True once the page has called `desktop_ready` (reset on every page load).
    pub ready: AtomicBool,
    /// A route that arrived (deep link, menu) before the page was listening.
    pub pending_route: Mutex<Option<String>>,
    pub live: Mutex<LiveState>,
    pub tray_status: StatusSlot,
    /// Debounce: the global shortcut and the menu accelerator can both fire.
    pub last_palette: Mutex<Option<Instant>>,
    /// The global shortcut currently registered, if any.
    pub shortcut: Mutex<Option<String>>,
}
