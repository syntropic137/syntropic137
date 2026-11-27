"""#1661: the lifecycle webhook is on with both settings, off with neither, and refused with one."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_shared.settings import get_settings, reset_settings
from syn_shared.settings.lifecycle_webhook import (
    ENV_SYN_LIFECYCLE_WEBHOOK_SECRET,
    ENV_SYN_LIFECYCLE_WEBHOOK_URL,
    LifecycleWebhookSettings,
)

pytestmark = pytest.mark.unit

_URL = "https://hooks.example.com/syn/lifecycle?tenant=t-7"
_SECRET = "whsec-0f3a-not-a-real-key"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, raising=False)
    monkeypatch.delenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, raising=False)


def _settings() -> LifecycleWebhookSettings:
    return LifecycleWebhookSettings(_env_file=None)


def test_both_unset_is_off() -> None:
    assert _settings().webhook is None


def test_blank_values_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A copied .env.example carries both as empty strings; that must mean off."""
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, "")
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, "  ")
    assert _settings().webhook is None


# The secret is an opaque HMAC key: padding and a trailing newline are part of it.
@pytest.mark.parametrize("secret", [_SECRET, f"  {_SECRET}  ", f"{_SECRET}\n"])
def test_both_set_is_on_through_the_composed_settings(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, _URL)
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, secret)
    reset_settings()
    try:
        webhook = get_settings().lifecycle_webhook.webhook
    finally:
        reset_settings()
    assert webhook is not None
    assert webhook.url == _URL
    assert webhook.secret.get_secret_value() == secret


def test_only_the_url_names_the_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, _URL)
    with pytest.raises(ValidationError) as caught:
        _settings()
    assert f"{ENV_SYN_LIFECYCLE_WEBHOOK_SECRET} is not" in str(caught.value)
    assert _URL not in str(caught.value)


def test_only_the_secret_names_the_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, _SECRET)
    with pytest.raises(ValidationError) as caught:
        _settings()
    assert f"{ENV_SYN_LIFECYCLE_WEBHOOK_URL} is not" in str(caught.value)
    assert _SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    ["ftp://hooks.example.com/syn", "hooks.example.com/syn", "file:///etc/passwd", "https://"],
)
def test_a_url_that_is_not_http_or_https_is_refused(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, url)
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, _SECRET)
    with pytest.raises(ValidationError) as caught:
        _settings()
    assert "must be an http or https URL" in str(caught.value)
    assert _SECRET not in str(caught.value)


@pytest.mark.parametrize("url", ["http://receiver:8080/hook", "https://hooks.example.com"])
def test_http_and_https_are_accepted(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, url)
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, _SECRET)
    webhook = _settings().webhook
    assert webhook is not None
    assert webhook.url == url


def test_the_secret_is_not_in_any_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, _URL)
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, _SECRET)
    settings = _settings()
    assert settings.webhook is not None
    for text in (repr(settings), str(settings), repr(settings.webhook), str(settings.webhook)):
        assert _SECRET not in text
