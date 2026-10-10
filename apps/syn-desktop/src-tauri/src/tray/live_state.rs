//! The connection state the web app reports for the tray dot.

use std::str::FromStr;

use serde::{Deserialize, Serialize};

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
    pub(super) fn rgb(self) -> [u8; 3] {
        match self {
            Self::Live => [46, 213, 115],
            Self::Connecting => [245, 184, 46],
            Self::Offline => [240, 82, 82],
            Self::Fixtures => [110, 160, 255],
        }
    }
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
}
