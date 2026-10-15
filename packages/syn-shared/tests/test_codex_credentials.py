"""Which codex credential a codex phase gets, and the file a key becomes (#1971)."""

from __future__ import annotations

import json

import pytest

from syn_shared.codex_auth_file import CODEX_AUTH_FILE_FORMAT
from syn_shared.codex_credential_port import (
    CodexCredentialFileClassification,
    CodexCredentialFileFormat,
    CodexCredentialFileKind,
)
from syn_shared.codex_credentials import (
    CodexCredentialSource,
    resolve_codex_credential,
)


def codex_api_key_auth_json(api_key: str) -> str:
    return CODEX_AUTH_FILE_FORMAT.api_key_credential_file(api_key)


pytestmark = pytest.mark.unit

_AUTH_JSON = '{"auth_mode":"chatgpt","tokens":{"access_token":"a","refresh_token":"r"}}'
_KEY = "sk-proj-fake-key-for-resolver-tests"


class TestPrecedence:
    def test_auth_json_only(self) -> None:
        resolved = resolve_codex_credential(codex_auth_json=_AUTH_JSON, openai_api_key=None)
        assert resolved is not None
        assert resolved.auth_json == _AUTH_JSON
        assert resolved.source is CodexCredentialSource.CODEX_AUTH_JSON
        assert resolved.both_configured is False

    def test_key_only_becomes_api_key_auth_json(self) -> None:
        resolved = resolve_codex_credential(codex_auth_json=None, openai_api_key=_KEY)
        assert resolved is not None
        assert resolved.source is CodexCredentialSource.OPENAI_API_KEY
        assert json.loads(resolved.auth_json) == {"auth_mode": "apikey", "OPENAI_API_KEY": _KEY}
        assert resolved.both_configured is False

    def test_both_auth_json_wins_and_says_so(self) -> None:
        resolved = resolve_codex_credential(codex_auth_json=_AUTH_JSON, openai_api_key=_KEY)
        assert resolved is not None
        assert resolved.auth_json == _AUTH_JSON
        assert resolved.source is CodexCredentialSource.CODEX_AUTH_JSON
        assert resolved.both_configured is True
        # The losing key is not smuggled into the file that is staged.
        assert _KEY not in resolved.auth_json

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_neither(self, blank: str | None) -> None:
        assert resolve_codex_credential(codex_auth_json=blank, openai_api_key=blank) is None

    def test_blank_auth_json_falls_back_to_the_key(self) -> None:
        resolved = resolve_codex_credential(codex_auth_json="  ", openai_api_key=_KEY)
        assert resolved is not None
        assert resolved.source is CodexCredentialSource.OPENAI_API_KEY

    def test_blank_key_with_auth_json_is_not_both(self) -> None:
        resolved = resolve_codex_credential(codex_auth_json=_AUTH_JSON, openai_api_key="  ")
        assert resolved is not None
        assert resolved.both_configured is False

    def test_key_whitespace_is_stripped(self) -> None:
        resolved = resolve_codex_credential(codex_auth_json=None, openai_api_key=f"  {_KEY}\n")
        assert resolved is not None
        assert json.loads(resolved.auth_json)["OPENAI_API_KEY"] == _KEY


class TestSynthesisedFile:
    """The shape `codex login --with-api-key` writes with codex-cli 0.160.1."""

    def test_exact_keys_and_values(self) -> None:
        parsed = json.loads(codex_api_key_auth_json(_KEY))
        assert parsed == {"auth_mode": "apikey", "OPENAI_API_KEY": _KEY}

    def test_key_with_json_metacharacters_round_trips(self) -> None:
        nasty = 'sk-"quoted"\\back\nslash'
        assert json.loads(codex_api_key_auth_json(nasty))["OPENAI_API_KEY"] == nasty

    def test_single_line(self) -> None:
        assert "\n" not in codex_api_key_auth_json(_KEY)


class TestNeverLeaks:
    def test_repr_omits_the_credential(self) -> None:
        for resolved in (
            resolve_codex_credential(codex_auth_json=None, openai_api_key=_KEY),
            resolve_codex_credential(codex_auth_json=_AUTH_JSON, openai_api_key=_KEY),
        ):
            assert resolved is not None
            assert _KEY not in repr(resolved)
            assert "access_token" not in repr(resolved)


class _RecordingFormat:
    """A port double: proves precedence depends on the port, not on codex's format."""

    def __init__(self) -> None:
        self.serialised: list[str] = []

    def api_key_credential_file(self, api_key: str) -> str:
        self.serialised.append(api_key)
        return "<double-file>"

    def classify(self, credential_file: str) -> CodexCredentialFileClassification:
        return CodexCredentialFileClassification(CodexCredentialFileKind.TOKENS)


class TestPort:
    def test_the_adapter_satisfies_the_port(self) -> None:
        port: CodexCredentialFileFormat = CODEX_AUTH_FILE_FORMAT
        assert json.loads(port.api_key_credential_file(_KEY))["OPENAI_API_KEY"] == _KEY

    def test_the_key_becomes_whatever_the_port_says(self) -> None:
        double = _RecordingFormat()
        resolved = resolve_codex_credential(
            codex_auth_json=None, openai_api_key=_KEY, credential_format=double
        )
        assert resolved is not None
        assert resolved.auth_json == "<double-file>"
        assert double.serialised == [_KEY]

    def test_auth_json_is_never_reserialised(self) -> None:
        double = _RecordingFormat()
        resolve_codex_credential(
            codex_auth_json=_AUTH_JSON, openai_api_key=_KEY, credential_format=double
        )
        assert double.serialised == []
