"""Pytest configuration for syn-dashboard tests.

This module configures the test environment, including setting up
the recordings directory for recording-based tests.
"""

from __future__ import annotations

import os
from pathlib import Path

# =============================================================================
# RECORDINGS DIRECTORY SETUP
# =============================================================================
# Set recordings directory for agentic_events when running from AEF
# This allows loading recordings in tests without specifying full paths

_SYN_ROOT = Path(__file__).parent.parent.parent.parent
_RECORDINGS_DIR = (
    _SYN_ROOT / "lib/agentic-primitives/providers/workspaces/claude-cli/fixtures/recordings"
)

if _RECORDINGS_DIR.exists() and "AGENTIC_RECORDINGS_DIR" not in os.environ:
    os.environ["AGENTIC_RECORDINGS_DIR"] = str(_RECORDINGS_DIR)
