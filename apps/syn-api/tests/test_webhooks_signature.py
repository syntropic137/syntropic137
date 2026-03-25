"""Unit tests for webhook signature verification and rate limiting."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from syn_api.routes.webhooks.signature import (
    _check_sig_rate_limit,
    _record_sig_failure,
    _sig_failures,
    _verify_signature,
    verify_webhook_signature,
)
from syn_api.types import Err, Ok


@pytest.fixture(autouse=True)
def _clear_rate_limits() -> None:
    """Reset rate-limit state between tests."""
    _sig_failures.clear()


# --- _verify_signature ---


def test_verify_signature_valid_hmac() -> None:
    body = b'{"action": "opened"}'
    secret = "test-secret"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, sig, secret) is True


def test_verify_signature_missing_signature_raises() -> None:
    with pytest.raises(ValueError, match="Missing webhook signature"):
        _verify_signature(b"body", None, "secret")


def test_verify_signature_wrong_hmac_raises() -> None:
    with pytest.raises(ValueError, match="Invalid webhook signature"):
        _verify_signature(b"body", "sha256=wrong", "secret")


def test_verify_signature_empty_secret_raises() -> None:
    with pytest.raises(ValueError, match="Webhook secret not configured"):
        _verify_signature(b"body", "sha256=abc", "")


# --- verify_webhook_signature ---


def test_verify_webhook_signature_returns_ok_on_valid() -> None:
    body = b'{"action": "opened"}'
    secret = "test-secret"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    with patch("syn_api.routes.webhooks.signature.get_github_settings") as mock_settings:
        mock_settings.return_value.webhook_secret.get_secret_value.return_value = secret
        result = verify_webhook_signature(body, sig)

    assert isinstance(result, Ok)


def test_verify_webhook_signature_returns_err_on_invalid() -> None:
    with patch("syn_api.routes.webhooks.signature.get_github_settings") as mock_settings:
        mock_settings.return_value.webhook_secret.get_secret_value.return_value = "secret"
        result = verify_webhook_signature(b"body", "sha256=wrong")

    assert isinstance(result, Err)
    assert "Invalid webhook signature" in (result.message or "")


def test_verify_webhook_signature_returns_err_on_missing_sig() -> None:
    with patch("syn_api.routes.webhooks.signature.get_github_settings") as mock_settings:
        mock_settings.return_value.webhook_secret.get_secret_value.return_value = "secret"
        result = verify_webhook_signature(b"body", None)

    assert isinstance(result, Err)
    assert "Missing" in (result.message or "")


# --- Rate limiting ---


def test_check_rate_limit_allows_under_threshold() -> None:
    for _ in range(4):
        _record_sig_failure("1.2.3.4")
    # Should not raise — 4 < 5
    _check_sig_rate_limit("1.2.3.4")


def test_check_rate_limit_blocks_at_threshold() -> None:
    for _ in range(5):
        _record_sig_failure("1.2.3.4")

    with pytest.raises(HTTPException) as exc_info:
        _check_sig_rate_limit("1.2.3.4")
    assert exc_info.value.status_code == 429


def test_check_rate_limit_different_ips_independent() -> None:
    for _ in range(5):
        _record_sig_failure("1.2.3.4")

    # Different IP should not be affected
    _check_sig_rate_limit("5.6.7.8")
