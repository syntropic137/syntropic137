"""Tests for the codex-auth clipboard helper (format + parse logic)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from scripts.copy_codex_auth import _build_payload, _load_compact

from syn_shared.env_constants import ENV_CODEX_AUTH_JSON

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "auth.json"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_compact_collapses_multiline_json(tmp_path: Path) -> None:
    path = _write(tmp_path, '{\n  "auth_mode": "chatgpt",\n  "token": "abc"\n}\n')
    compact, auth_mode = _load_compact(path)
    assert compact == '{"auth_mode":"chatgpt","token":"abc"}'
    assert "\n" not in compact
    assert auth_mode == "chatgpt"


def test_load_compact_auth_mode_defaults_when_absent(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"token": "abc"}')
    _, auth_mode = _load_compact(path)
    assert auth_mode == "?"


def test_load_compact_missing_file_exits_with_guidance(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        _load_compact(tmp_path / "auth.json")
    assert "codex login" in str(exc.value)


def test_load_compact_rejects_invalid_json(tmp_path: Path) -> None:
    path = _write(tmp_path, "not json")
    with pytest.raises(SystemExit) as exc:
        _load_compact(path)
    assert "not valid JSON" in str(exc.value)


def test_load_compact_rejects_non_object(tmp_path: Path) -> None:
    path = _write(tmp_path, "[1, 2, 3]")
    with pytest.raises(SystemExit) as exc:
        _load_compact(path)
    assert "JSON object" in str(exc.value)


def test_build_payload_default_is_raw_value() -> None:
    compact = '{"auth_mode":"chatgpt"}'
    assert _build_payload(compact, dotenv=False) == compact


def test_build_payload_dotenv_wraps_single_quoted_line() -> None:
    compact = '{"auth_mode":"chatgpt"}'
    assert _build_payload(compact, dotenv=True) == f"{ENV_CODEX_AUTH_JSON}='{compact}'"


def test_build_payload_dotenv_rejects_embedded_single_quote() -> None:
    compact = json.dumps({"note": "it's"}, separators=(",", ":"))
    with pytest.raises(SystemExit) as exc:
        _build_payload(compact, dotenv=True)
    assert "single quote" in str(exc.value)
