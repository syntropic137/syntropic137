"""The freshness probe must never leak, never raise, and never cry wolf.

Each test here isolates ONE behaviour, so that removing any single guard in
``codex_auth_status`` fails a named test rather than being absorbed by a
neighbour. Two conditions checked jointly prove neither: see the "green test
suite is not evidence" section of docs/testing/release-validation.md.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from syn_shared.codex_auth_status import (
    WARN_THRESHOLD_HOURS,
    CodexAuthState,
    describe_codex_auth,
)
from syn_shared.codex_credentials import CodexCredentialSource

_SECRET = "sk-super-secret-refresh-token-value"


def _jwt(exp_offset_hours: float) -> str:
    """A JWT-shaped access token expiring `exp_offset_hours` from now."""
    claims = json.dumps({"exp": int(time.time() + exp_offset_hours * 3600)}).encode()
    payload = base64.urlsafe_b64encode(claims).rstrip(b"=").decode()
    return f"header.{payload}.signature"


def _auth(access_token: str) -> str:
    return json.dumps(
        {
            "auth_mode": "chatgpt",
            "tokens": {"access_token": access_token, "refresh_token": _SECRET},
        }
    )


@pytest.mark.unit
class TestState:
    def test_comfortable_headroom_is_ok(self) -> None:
        assert describe_codex_auth(_auth(_jwt(240))).state is CodexAuthState.OK

    def test_inside_the_window_is_expiring(self) -> None:
        s = describe_codex_auth(_auth(_jwt(WARN_THRESHOLD_HOURS - 1)))
        assert s.state is CodexAuthState.EXPIRING

    def test_past_expiry_is_expired(self) -> None:
        s = describe_codex_auth(_auth(_jwt(-3)))
        assert s.state is CodexAuthState.EXPIRED
        assert s.expires_in_hours is not None and s.expires_in_hours < 0

    def test_absent_is_its_own_state(self) -> None:
        """Distinguishable from expired: nothing to re-mint, it was never set."""
        for empty in (None, "", "   "):
            assert describe_codex_auth(empty).state is CodexAuthState.ABSENT

    def test_boundary_belongs_to_expiring_not_ok(self) -> None:
        """Pins which side of the threshold the boundary falls on."""
        assert (
            describe_codex_auth(_auth(_jwt(WARN_THRESHOLD_HOURS - 0.01))).state
            is CodexAuthState.EXPIRING
        )


@pytest.mark.unit
class TestNeedsAttention:
    """UNREADABLE must NOT be actionable, or an access-token setup cries wolf."""

    def test_expired_and_expiring_need_attention(self) -> None:
        assert describe_codex_auth(_auth(_jwt(-1))).needs_attention
        assert describe_codex_auth(_auth(_jwt(1))).needs_attention

    def test_ok_does_not(self) -> None:
        assert not describe_codex_auth(_auth(_jwt(240))).needs_attention

    def test_unreadable_does_not(self) -> None:
        """An access-token credential has no JWT and is legitimately unreadable.

        This used an API-key file until #1971, which now has its own state
        (TestApiKey); an opaque, non-JWT access token is the unreadable case.
        """
        raw = _auth("opaque-access-token-not-a-jwt")
        s = describe_codex_auth(raw)
        assert s.state is CodexAuthState.UNREADABLE
        assert not s.needs_attention

    def test_absent_does_not(self) -> None:
        """Deliberately unconfigured is a choice, not a fault to alarm on."""
        assert not describe_codex_auth(None).needs_attention


@pytest.mark.unit
class TestNeverLeaks:
    """The whole point is reporting freshness WITHOUT handling the secret."""

    def test_no_token_material_in_any_field(self) -> None:
        s = describe_codex_auth(_auth(_jwt(100)))
        blob = s.model_dump_json()
        assert _SECRET not in blob
        assert "header." not in blob
        assert "signature" not in blob

    def test_no_token_material_when_expired(self) -> None:
        """The failure path is where a careless implementation echoes the input."""
        blob = describe_codex_auth(_auth(_jwt(-99))).model_dump_json()
        assert _SECRET not in blob

    def test_no_token_material_when_unparseable(self) -> None:
        blob = describe_codex_auth(
            f'{{"tokens": {{"refresh_token": "{_SECRET}"}}'
        ).model_dump_json()
        assert _SECRET not in blob


@pytest.mark.unit
class TestNeverRaises:
    """Called from /health. A probe that can take the endpoint down is worse
    than no probe, so every malformed shape must resolve to a state."""

    @pytest.mark.parametrize(
        "raw",
        [
            "not json at all",
            "[]",
            "123",
            '"a string"',
            "{}",
            '{"tokens": null}',
            '{"tokens": "wrong type"}',
            '{"tokens": {"access_token": null}}',
            '{"tokens": {"access_token": "not-a-jwt"}}',
            '{"tokens": {"access_token": "a.b"}}',
            '{"tokens": {"access_token": "a.!!!notbase64!!!.c"}}',
            '{"tokens": {"access_token": "a.eyJubyI6ImV4cCJ9.c"}}',
        ],
    )
    def test_malformed_input_yields_a_state(self, raw: str) -> None:
        assert describe_codex_auth(raw).state in set(CodexAuthState)

    def test_non_numeric_exp_is_unreadable_not_a_crash(self) -> None:
        payload = base64.urlsafe_b64encode(json.dumps({"exp": "soon"}).encode()).rstrip(b"=")
        raw = _auth(f"h.{payload.decode()}.s")
        assert describe_codex_auth(raw).state is CodexAuthState.UNREADABLE


@pytest.mark.unit
class TestDetail:
    def test_expiring_detail_names_the_recovery_command(self) -> None:
        """A warning that does not say what to do is an alarm, not a signal."""
        assert "just codex-reauth" in describe_codex_auth(_auth(_jwt(2))).detail

    def test_expired_detail_says_it_is_failing_now(self) -> None:
        d = describe_codex_auth(_auth(_jwt(-2))).detail
        assert "EXPIRED" in d
        assert "just codex-reauth" in d


_API_KEY = "sk-proj-fake-key-for-status-tests"


@pytest.mark.unit
class TestApiKey:
    """An API key has no expiry: its own state, never UNREADABLE (#1971)."""

    def test_apikey_auth_json_is_api_key_state(self) -> None:
        raw = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": _API_KEY})
        s = describe_codex_auth(raw)
        assert s.state is CodexAuthState.API_KEY
        assert s.expires_at is None
        assert s.expires_in_hours is None

    def test_key_from_openai_api_key_names_that_setting(self) -> None:
        raw = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": _API_KEY})
        s = describe_codex_auth(raw, source=CodexCredentialSource.OPENAI_API_KEY)
        assert s.state is CodexAuthState.API_KEY
        assert "from OPENAI_API_KEY" in s.detail

    def test_mode_less_file_with_a_key_is_api_key(self) -> None:
        """codex's resolved_mode: no auth_mode plus a key string means API key."""
        s = describe_codex_auth(json.dumps({"OPENAI_API_KEY": _API_KEY}))
        assert s.state is CodexAuthState.API_KEY

    def test_null_key_in_a_chatgpt_file_is_not_api_key(self) -> None:
        """Older ChatGPT auth.json files carry "OPENAI_API_KEY": null."""
        raw = json.dumps(
            {"OPENAI_API_KEY": None, "tokens": {"access_token": _jwt(240), "refresh_token": "r"}}
        )
        assert describe_codex_auth(raw).state is CodexAuthState.OK

    def test_explicit_chatgpt_mode_wins_over_a_stray_key(self) -> None:
        raw = json.dumps(
            {
                "auth_mode": "chatgpt",
                "OPENAI_API_KEY": _API_KEY,
                "tokens": {"access_token": _jwt(240), "refresh_token": "r"},
            }
        )
        assert describe_codex_auth(raw).state is CodexAuthState.OK

    def test_api_key_does_not_need_attention(self) -> None:
        raw = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": _API_KEY})
        assert not describe_codex_auth(raw).needs_attention

    @pytest.mark.parametrize("source", list(CodexCredentialSource))
    def test_key_never_in_any_field(self, source: CodexCredentialSource) -> None:
        raw = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": _API_KEY})
        assert _API_KEY not in describe_codex_auth(raw, source=source).model_dump_json()

    def test_absent_detail_names_both_settings(self) -> None:
        d = describe_codex_auth(None).detail
        assert "CODEX_AUTH_JSON" in d
        assert "OPENAI_API_KEY" in d
