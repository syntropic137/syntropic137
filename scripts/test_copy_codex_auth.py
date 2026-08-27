"""Tests for the codex-auth clipboard helper (format + parse logic)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from scripts.copy_codex_auth import _build_payload, _load_compact, _token_status

from syn_shared.env_constants import ENV_CODEX_AUTH_JSON

if TYPE_CHECKING:
    from pathlib import Path


# Marked at module scope: this file sat outside pytest testpaths, so no CI
# job collected it and nothing here needed a marker. Collected now, an
# unmarked test is one no job runs - which the census gate refuses.
pytestmark = pytest.mark.unit


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "auth.json"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_compact_collapses_multiline_json(tmp_path: Path) -> None:
    path = _write(tmp_path, '{\n  "auth_mode": "chatgpt",\n  "token": "abc"\n}\n')
    compact, auth_mode, _data = _load_compact(path)
    assert compact == '{"auth_mode":"chatgpt","token":"abc"}'
    assert "\n" not in compact
    assert auth_mode == "chatgpt"


def test_load_compact_auth_mode_defaults_when_absent(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"token": "abc"}')
    _, auth_mode, _data = _load_compact(path)
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


@pytest.mark.unit
class TestTokenStatus:
    """The freshness report is the whole point: it must never leak, and must
    call an expired token expired.

    A burned token copies successfully and fails much later inside a container,
    so reporting expiry at copy time is what turns a container-log dig into one
    line of output.
    """

    def _auth(self, exp_offset: float) -> dict[str, object]:
        import base64
        import json as _json
        import time as _time

        claims = _json.dumps({"exp": int(_time.time() + exp_offset)}).encode()
        body = base64.urlsafe_b64encode(claims).rstrip(b"=").decode()
        return {
            "tokens": {"access_token": f"aaa.{body}.bbb"},
            "last_refresh": "2026-08-24T01:27:31Z",
        }

    def test_valid_token_reports_time_left(self) -> None:
        lines = _token_status(self._auth(3600))
        assert any("valid" in ln for ln in lines)
        assert not any("EXPIRED" in ln for ln in lines)

    def test_expired_token_says_expired_and_says_what_to_do(self) -> None:
        lines = _token_status(self._auth(-3600))
        assert any("EXPIRED" in ln for ln in lines)
        assert any("codex login" in ln for ln in lines)

    def test_never_emits_token_material(self) -> None:
        """A status line that echoed the token would leak it into scrollback."""
        auth = self._auth(3600)
        token = auth["tokens"]["access_token"]  # type: ignore[index]
        joined = "\n".join(_token_status(auth))
        assert str(token) not in joined
        assert "aaa." not in joined

    def test_malformed_token_does_not_raise(self) -> None:
        """A copy tool that crashes on a odd auth file is worse than no report."""
        assert _token_status({"tokens": {"access_token": "not-a-jwt"}}) == []
        assert _token_status({}) == []
        assert _token_status({"tokens": "wrong-type"}) == []
