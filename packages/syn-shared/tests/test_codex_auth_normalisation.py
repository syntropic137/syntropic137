"""CODEX_AUTH_JSON must survive being pasted by a human.

This credential is a ~4KB single-line JSON blob that someone copies out of
~/.codex/auth.json and pastes into a secret store by hand. Editors mangle it in
predictable ways, and the result is a credential that LOOKS present and then
fails deep inside workspace provisioning - the worst failure shape for a secret,
because nothing points at the secret as the cause.

The CSV case below is not hypothetical: it is exactly what a real 1Password
paste produced on 2026-08-17 (4193 stored bytes for a 4163-byte value).
"""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from syn_shared.settings.config import Settings

_REAL_SHAPE = json.dumps(
    {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {"access_token": "xxx", "refresh_token": "yyy"},
        "last_refresh": "2026-08-17T00:00:00Z",
    },
    separators=(",", ":"),
)


def _normalise(raw: str) -> str:
    validator = Settings._normalise_codex_auth_json.__func__
    result = validator(Settings, SecretStr(raw))
    assert result is not None
    return result.get_secret_value()


@pytest.mark.unit
class TestCodexAuthNormalisation:
    def test_clean_value_passes_through(self) -> None:
        assert json.loads(_normalise(_REAL_SHAPE)) == json.loads(_REAL_SHAPE)

    def test_recovers_1password_csv_quoting(self) -> None:
        """The real-world failure: wrapped in quotes, inner quotes doubled."""
        mangled = '"' + _REAL_SHAPE.replace('"', '""') + '"'
        assert len(mangled) > len(_REAL_SHAPE)
        assert json.loads(_normalise(mangled)) == json.loads(_REAL_SHAPE)

    def test_recovers_dotenv_single_quotes(self) -> None:
        """Carried over from a `CODEX_AUTH_JSON='...'` .env line."""
        assert json.loads(_normalise("'" + _REAL_SHAPE + "'")) == json.loads(_REAL_SHAPE)

    def test_recovers_surrounding_whitespace_and_newlines(self) -> None:
        assert json.loads(_normalise(f"  {_REAL_SHAPE}\n")) == json.loads(_REAL_SHAPE)

    def test_output_is_always_compact_single_line(self) -> None:
        """Downstream writes this straight to ~/.codex/auth.json."""
        out = _normalise(f"  {_REAL_SHAPE}\n")
        assert "\n" not in out
        assert ", " not in out

    def test_empty_becomes_none_not_an_error(self) -> None:
        validator = Settings._normalise_codex_auth_json.__func__
        assert validator(Settings, SecretStr("   ")) is None
        assert validator(Settings, None) is None

    def test_unparseable_raises_rather_than_reaching_provisioning(self) -> None:
        """Fail at settings load, naming the credential - not opaquely later."""
        with pytest.raises(ValueError, match="CODEX_AUTH_JSON"):
            _normalise("not json at all")

    def test_non_object_json_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            _normalise("[1, 2, 3]")

    def test_error_names_the_recovery_action(self) -> None:
        """The message has to tell the reader what to actually do."""
        with pytest.raises(ValueError) as exc:
            _normalise("{broken")
        assert "codex-auth-clip" in str(exc.value)
