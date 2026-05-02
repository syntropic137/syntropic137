"""Unit tests for webhook signature verification.

IP-based rate limiting is handled at the edge (NGINX/Cloudflare), not in the app.
"""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import patch

import pytest

from syn_api.routes.webhooks.signature import (
    _verify_signature,
    verify_webhook_signature,
)
from syn_api.types import Err, Ok

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
