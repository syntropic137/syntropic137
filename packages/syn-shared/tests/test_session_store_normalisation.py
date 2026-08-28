"""SYN_SESSION_STORE_URL must survive being pasted by a human.

The URL and token are hand-entered into a vault. Whitespace damage there is
invisible in the vault UI, invisible in most log output, and does NOT fail
loudly: a trailing space turns the upload target into
``http://host:18090 /v1/sessions/batch``, every upload errors, capture records
FAILED, and because capture is FAIL-OPEN the workflow still goes green. Nothing
anywhere names the space as the cause.

This is not hypothetical. On 2026-08-21 the dev vault held 27 bytes for a
26-byte URL. Reproduced from inside the workspace image: the trailing-space
value returned a curl error, the trimmed value returned 200. Four other causes
of "zero captured sessions" had already been found and fixed by then, each
producing an identical symptom - which is why the settings layer normalises
instead of trusting the input.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from syn_shared.settings.session_store import SessionStoreSettings

_URL = "http://100.112.178.5:18090"


def _url_of(raw: str) -> str | None:
    return SessionStoreSettings(url=raw).url


@pytest.mark.unit
class TestUrlWhitespaceIsTrimmed:
    def test_trailing_space_is_stripped(self) -> None:
        """The exact shape observed in the vault."""
        assert _url_of(f"{_URL} ") == _URL

    def test_leading_space_is_stripped(self) -> None:
        assert _url_of(f" {_URL}") == _URL

    def test_trailing_newline_is_stripped(self) -> None:
        """A copied line often carries its line ending."""
        assert _url_of(f"{_URL}\n") == _URL
        assert _url_of(f"{_URL}\r\n") == _URL

    def test_surrounding_tabs_are_stripped(self) -> None:
        assert _url_of(f"\t{_URL}\t") == _URL

    def test_clean_value_is_unchanged(self) -> None:
        assert _url_of(_URL) == _URL

    def test_trimmed_url_keeps_capture_enabled(self) -> None:
        settings = SessionStoreSettings(url=f"{_URL} ")
        assert settings.is_enabled, "a trimmable URL must still enable capture"


@pytest.mark.unit
class TestInternalWhitespaceIsRejected:
    """Trimming the ends is unambiguous; a space in the middle is not.

    Silently mangling it would hide an operator error rather than surface it,
    and the resulting URL would be wrong in a way nobody could see.
    """

    def test_embedded_space_raises(self) -> None:
        with pytest.raises(ValueError, match="SYN_SESSION_STORE_URL"):
            SessionStoreSettings(url="http://100.112.178.5 :18090")

    def test_embedded_newline_raises(self) -> None:
        with pytest.raises(ValueError, match="whitespace"):
            SessionStoreSettings(url="http://100.112.178.5\n:18090")

    def test_error_names_the_variable_and_the_remedy(self) -> None:
        """The message has to tell the reader where to look."""
        with pytest.raises(ValueError) as exc:
            SessionStoreSettings(url="http://a b:18090")
        text = str(exc.value)
        assert "SYN_SESSION_STORE_URL" in text
        assert "vault" in text


@pytest.mark.unit
class TestTokenWhitespaceIsTrimmed:
    """A stray space in the token becomes a 401 at finalize, cause suppressed."""

    def test_trailing_space_is_stripped(self) -> None:
        settings = SessionStoreSettings(url=_URL, auth_token=SecretStr("tok-123 "))
        assert settings.auth_token is not None
        assert settings.auth_token.get_secret_value() == "tok-123"

    def test_newline_is_stripped(self) -> None:
        settings = SessionStoreSettings(url=_URL, auth_token=SecretStr("tok-123\n"))
        assert settings.auth_token is not None
        assert settings.auth_token.get_secret_value() == "tok-123"


@pytest.mark.unit
class TestDisabledStaysDisabled:
    """Normalisation must not accidentally switch capture on."""

    def test_whitespace_only_url_is_none(self) -> None:
        assert SessionStoreSettings(url="   ").url is None

    def test_whitespace_only_url_leaves_capture_off(self) -> None:
        assert not SessionStoreSettings(url="   ").is_enabled

    def test_unset_url_leaves_capture_off(self) -> None:
        assert not SessionStoreSettings().is_enabled
