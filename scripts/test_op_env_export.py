"""Tests for the 1Password environment export allowlist."""

from __future__ import annotations

from scripts.op_env_export import _KEYS


def test_codex_auth_json_is_exported_from_1password() -> None:
    assert "CODEX_AUTH_JSON" in _KEYS
