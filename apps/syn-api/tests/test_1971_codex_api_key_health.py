"""/health reports an OpenAI API key as its own codex credential state (#1971).

Driven through the real settings load, so the probe is tested against the
same precedence a codex phase gets: CODEX_AUTH_JSON first, OPENAI_API_KEY second.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from syn_api.services.health_probes import describe_codex_auth_health
from syn_shared.codex_auth_status import CodexAuthState
from syn_shared.env_constants import ENV_CODEX_AUTH_JSON, ENV_OPENAI_API_KEY
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.unit

_KEY = "sk-proj-fake-key-for-health-probe"
_CHATGPT_AUTH = json.dumps(
    {"auth_mode": "chatgpt", "tokens": {"access_token": "opaque", "refresh_token": "r"}}
)


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str, str], None]]:
    def apply(codex_auth_json: str, openai_api_key: str) -> None:
        monkeypatch.setenv(ENV_CODEX_AUTH_JSON, codex_auth_json)
        monkeypatch.setenv(ENV_OPENAI_API_KEY, openai_api_key)
        reset_settings()

    yield apply
    reset_settings()


def test_key_only_is_api_key_state(configure: Callable[[str, str], None]) -> None:
    configure("", _KEY)
    status = describe_codex_auth_health()
    assert status is not None
    assert status.state is CodexAuthState.API_KEY
    assert "OPENAI_API_KEY" in status.detail
    assert status.expires_at is None
    assert _KEY not in status.model_dump_json()


def test_auth_json_wins_over_the_key(configure: Callable[[str, str], None]) -> None:
    configure(_CHATGPT_AUTH, _KEY)
    status = describe_codex_auth_health()
    assert status is not None
    # The ChatGPT file is what a phase gets, so that is what is described.
    assert status.state is CodexAuthState.UNREADABLE
    assert _KEY not in status.model_dump_json()


def test_neither_is_absent(configure: Callable[[str, str], None]) -> None:
    configure("", "")
    status = describe_codex_auth_health()
    assert status is not None
    assert status.state is CodexAuthState.ABSENT
