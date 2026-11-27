"""A half-set lifecycle webhook must abort startup, not degrade it (#1661).

The settings are otherwise first built inside the subscription coordinator's
init, which is degradable and retried, so a URL with no secret would leave the
API reporting degraded on a loop with the webhook silently off. Same shape as
the workspace gate (#954).
"""

from __future__ import annotations

import pytest

from syn_api.services import lifecycle
from syn_api.types import Err, LifecycleError, Ok
from syn_shared.settings.lifecycle_webhook import (
    ENV_SYN_LIFECYCLE_WEBHOOK_SECRET,
    ENV_SYN_LIFECYCLE_WEBHOOK_URL,
)

pytestmark = pytest.mark.unit

_SECRET = "whsec-0f3a-not-a-real-key"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, raising=False)
    monkeypatch.delenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, raising=False)


async def test_a_secret_with_no_url_stops_the_critical_path_before_the_event_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, _SECRET)
    monkeypatch.setattr(lifecycle, "_validate_workspace_settings", lambda: Ok(None))

    async def event_store_reached() -> Ok[None]:
        raise AssertionError("startup went past a half-set lifecycle webhook")

    monkeypatch.setattr(lifecycle, "_init_event_store", event_store_reached)

    result = await lifecycle._init_critical_path()

    assert isinstance(result, Err)
    assert result.error is LifecycleError.VALIDATION_FAILED
    assert f"{ENV_SYN_LIFECYCLE_WEBHOOK_URL} is not" in result.message
    assert _SECRET not in result.message


def test_unset_passes() -> None:
    assert isinstance(lifecycle._validate_lifecycle_webhook_settings(), Ok)


def test_a_bad_scheme_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, "ftp://hooks.example.com/syn")
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, _SECRET)
    result = lifecycle._validate_lifecycle_webhook_settings()
    assert isinstance(result, Err)
    assert "http or https" in result.message
