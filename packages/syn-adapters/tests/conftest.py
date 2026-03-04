"""Pytest configuration for syn-adapters tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter


# =============================================================================
# CONFIGURE RECORDINGS PATH
# =============================================================================

# Set recordings directory for agentic_events when running from Syntropic137
_SYN_ROOT = Path(__file__).parent.parent.parent.parent
_RECORDINGS_DIR = (
    _SYN_ROOT / "lib/agentic-primitives/providers/workspaces/claude-cli/fixtures/recordings"
)

if _RECORDINGS_DIR.exists() and "AGENTIC_RECORDINGS_DIR" not in os.environ:
    os.environ["AGENTIC_RECORDINGS_DIR"] = str(_RECORDINGS_DIR)


# =============================================================================
# RECORDING FIXTURES
# =============================================================================


@pytest.fixture
def recording_adapter():
    """Factory fixture for RecordingEventStreamAdapter.

    Usage:
        def test_something(recording_adapter):
            adapter = recording_adapter("simple-bash")
            events = adapter.get_events()
    """
    from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter

    def _create(recording_name: str, **kwargs) -> RecordingEventStreamAdapter:
        return RecordingEventStreamAdapter(recording_name, **kwargs)

    return _create


@pytest.fixture
def simple_bash_adapter(recording_adapter) -> RecordingEventStreamAdapter:
    """Pre-loaded adapter with simple-bash recording.

    Usage:
        def test_something(simple_bash_adapter):
            events = simple_bash_adapter.get_events()
    """
    try:
        return recording_adapter("simple-bash")
    except FileNotFoundError:
        pytest.skip("simple-bash recording not available")


@pytest.fixture
def file_create_adapter(recording_adapter) -> RecordingEventStreamAdapter:
    """Pre-loaded adapter with file-create recording."""
    try:
        return recording_adapter("file-create")
    except FileNotFoundError:
        pytest.skip("file-create recording not available")


@pytest.fixture
def multi_tool_adapter(recording_adapter) -> RecordingEventStreamAdapter:
    """Pre-loaded adapter with multi-tool recording."""
    try:
        return recording_adapter("multi-tool")
    except FileNotFoundError:
        pytest.skip("multi-tool recording not available")
