"""The codex auth.json adapter: what each file shape is, without echoing it (#1971).

Shapes pinned to codex-rs at rust-v0.160.1 (see the adapter's docstring).
"""

from __future__ import annotations

import json

import pytest

from syn_shared.codex_auth_file import CODEX_AUTH_FILE_FORMAT
from syn_shared.codex_credential_port import CodexCredentialFileKind

pytestmark = pytest.mark.unit

_KEY = "sk-proj-fake-key-for-adapter-tests"


def _kind(value: object) -> CodexCredentialFileKind:
    return CODEX_AUTH_FILE_FORMAT.classify(json.dumps(value)).kind


class TestApiKeyMode:
    def test_usable_key(self) -> None:
        assert _kind({"auth_mode": "apikey", "OPENAI_API_KEY": _KEY}) is (
            CodexCredentialFileKind.API_KEY
        )

    @pytest.mark.parametrize(
        "file",
        [
            {"auth_mode": "apikey"},
            {"auth_mode": "apikey", "OPENAI_API_KEY": None},
            {"auth_mode": "apikey", "OPENAI_API_KEY": ""},
            {"auth_mode": "apikey", "OPENAI_API_KEY": "   "},
            # Mode-less with a present-but-blank key: codex resolves ApiKey.
            {"OPENAI_API_KEY": ""},
        ],
        ids=["missing", "null", "empty", "whitespace", "modeless-empty"],
    )
    def test_unusable_key_is_its_own_kind(self, file: dict[str, str | None]) -> None:
        assert _kind(file) is CodexCredentialFileKind.API_KEY_WITHOUT_KEY

    def test_mode_less_file_with_a_key_is_api_key(self) -> None:
        assert _kind({"OPENAI_API_KEY": _KEY}) is CodexCredentialFileKind.API_KEY

    def test_a_pat_field_wins_over_a_mode_less_key(self) -> None:
        assert _kind({"OPENAI_API_KEY": _KEY, "personal_access_token": "p"}) is (
            CodexCredentialFileKind.TOKENS
        )

    def test_the_written_file_classifies_as_api_key(self) -> None:
        written = CODEX_AUTH_FILE_FORMAT.api_key_credential_file(_KEY)
        assert CODEX_AUTH_FILE_FORMAT.classify(written).kind is CodexCredentialFileKind.API_KEY


class TestTokens:
    def test_chatgpt_login_with_extra_fields_is_tokens(self) -> None:
        """extra="allow" is load-bearing: real files carry fields not read here."""
        file = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {"id_token": "i", "access_token": "a", "refresh_token": "r"},
            "last_refresh": "2026-10-14T00:00:00Z",
            "some_future_field": {"x": 1},
        }
        found = CODEX_AUTH_FILE_FORMAT.classify(json.dumps(file))
        assert found.kind is CodexCredentialFileKind.TOKENS
        assert found.access_token_expiry is None


class TestMalformed:
    @pytest.mark.parametrize(
        ("raw", "kind"),
        [
            ("not json", CodexCredentialFileKind.NOT_JSON),
            ("[]", CodexCredentialFileKind.NOT_AN_OBJECT),
            ('{"tokens": "wrong type"}', CodexCredentialFileKind.MALFORMED),
            ('{"auth_mode": ["apikey"]}', CodexCredentialFileKind.MALFORMED),
            (f'{{"OPENAI_API_KEY": 12, "x": "{_KEY}"}}', CodexCredentialFileKind.MALFORMED),
        ],
    )
    def test_shapes(self, raw: str, kind: CodexCredentialFileKind) -> None:
        found = CODEX_AUTH_FILE_FORMAT.classify(raw)
        assert found.kind is kind
        assert _KEY not in repr(found)
