"""Webhook signature verification. IP-based rate limiting is handled at the edge (NGINX/Cloudflare)."""

from __future__ import annotations

import hashlib
import hmac
import logging

from syn_api._wiring import get_github_settings
from syn_api.types import Err, GitHubError, Ok, Result

logger = logging.getLogger(__name__)


def _verify_signature(body: bytes, signature: str | None, webhook_secret: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature.

    Returns True when the signature is valid.
    Raises ``ValueError`` with a human-readable message on any failure.
    """
    if not webhook_secret:
        raise ValueError("Webhook secret not configured, rejecting unverified payload")
    if not signature:
        raise ValueError("Missing webhook signature")

    expected = "sha256=" + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid webhook signature")
    return True


def verify_webhook_signature(body: bytes, signature: str | None) -> Result[bool, GitHubError]:
    """Verify webhook HMAC signature, returning Result instead of raising."""
    try:
        secret = get_github_settings().webhook_secret.get_secret_value()
        _verify_signature(body, signature, secret)
    except ValueError as exc:
        return Err(GitHubError.INVALID_SIGNATURE, message=str(exc))
    except Exception:
        logger.exception("Failed to verify webhook signature")
        return Err(
            GitHubError.INVALID_SIGNATURE,
            message="Signature verification failed, rejecting payload",
        )
    return Ok(True)
