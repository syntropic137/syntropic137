"""Tests for the 1Password environment export allowlist."""

from __future__ import annotations

import pytest
from scripts.op_env_export import _KEYS

# Marked at module scope: this file sat outside pytest testpaths, so no CI
# job collected it and nothing here needed a marker. Collected now, an
# unmarked test is one no job runs - which the census gate refuses.
pytestmark = pytest.mark.unit


def test_codex_auth_json_is_exported_from_1password() -> None:
    assert "CODEX_AUTH_JSON" in _KEYS


def test_openai_api_key_is_exported_from_1password() -> None:
    # The codex API-key fallback (#1971) must resolve from the vault like
    # CODEX_AUTH_JSON, or a vault-only deployment never sees it.
    assert "OPENAI_API_KEY" in _KEYS
