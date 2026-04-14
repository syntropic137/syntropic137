"""Webhook signature verification and rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import HTTPException

from syn_api._wiring import get_github_settings
from syn_api.types import Err, GitHubError, Ok, Result

logger = logging.getLogger(__name__)

# --- Signature-failure rate limiter ---
_MAX_FAILURES = 5
_WINDOW_SECONDS = 60
# PERFORMANCE: per-instance tracking, resets on restart. Multi-instance: effective limit multiplied by instance count (acceptable for rate limiting)
_sig_failures: dict[str, list[float]] = {}

_MAX_TRACKED_IPS = 10_000


def _evict_stale_sig_failures() -> None:
    """Prune stale entries to prevent unbounded growth."""
    if len(_sig_failures) <= _MAX_TRACKED_IPS:
        return
    now = time.monotonic()
    stale = [
        ip
        for ip, attempts in _sig_failures.items()
        if not any(now - t < _WINDOW_SECONDS for t in attempts)
    ]
    for ip in stale:
        del _sig_failures[ip]
    if stale:
        logger.info("Pruned %d stale signature failure entries", len(stale))


def _check_sig_rate_limit(client_ip: str) -> None:
    """Raise 429 if this IP has too many recent signature failures."""
    _evict_stale_sig_failures()
    now = time.monotonic()
    attempts = _sig_failures.get(client_ip)
    if attempts is None:
        return
    # Prune old attempts
    recent = [t for t in attempts if now - t < _WINDOW_SECONDS]
    if not recent:
        del _sig_failures[client_ip]
        return
    _sig_failures[client_ip] = recent
    if len(recent) >= _MAX_FAILURES:
        logger.warning("Webhook rate limit: %s blocked (%d failures)", client_ip, len(recent))
        raise HTTPException(status_code=429, detail="Too many failed signature attempts")


def _record_sig_failure(client_ip: str) -> None:
    """Record a signature verification failure for rate limiting."""
    if client_ip not in _sig_failures:
        _sig_failures[client_ip] = []
    _sig_failures[client_ip].append(time.monotonic())


def _verify_signature(body: bytes, signature: str | None, webhook_secret: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature.

    Returns True when the signature is valid.
    Raises ``ValueError`` with a human-readable message on any failure.
    """
    if not webhook_secret:
        raise ValueError("Webhook secret not configured — rejecting unverified payload")
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
            message="Signature verification failed — rejecting payload",
        )
    return Ok(True)
