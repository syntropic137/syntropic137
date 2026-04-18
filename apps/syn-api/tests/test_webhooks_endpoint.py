"""Unit tests for webhook HTTP endpoint helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from syn_api.routes.webhooks.endpoint import (
    _build_webhook_response,
    _handle_ping,
    _raise_for_webhook_error,
)
from syn_api.types import Err, GitHubError, WebhookResult

# --- _handle_ping ---


def test_handle_ping_valid_json() -> None:
    body = b'{"zen": "Keep it logically awesome."}'
    result = _handle_ping(body)
    assert result == {"status": "pong", "zen": "Keep it logically awesome."}


def test_handle_ping_invalid_json_returns_empty_zen() -> None:
    result = _handle_ping(b"not-json")
    assert result == {"status": "pong", "zen": ""}


# --- _raise_for_webhook_error ---


def test_raise_for_webhook_error_signature_gives_401() -> None:
    err = Err(GitHubError.INVALID_SIGNATURE, message="bad sig")
    with pytest.raises(HTTPException) as exc_info:
        _raise_for_webhook_error(err)
    assert exc_info.value.status_code == 401


def test_raise_for_webhook_error_payload_gives_400() -> None:
    err = Err(GitHubError.INVALID_PAYLOAD, message="bad json")
    with pytest.raises(HTTPException) as exc_info:
        _raise_for_webhook_error(err)
    assert exc_info.value.status_code == 400


def test_raise_for_webhook_error_other_gives_500() -> None:
    err = Err(GitHubError.PROCESSING_FAILED, message="boom")
    with pytest.raises(HTTPException) as exc_info:
        _raise_for_webhook_error(err)
    assert exc_info.value.status_code == 500


# --- _build_webhook_response ---


def test_build_webhook_response_with_triggers() -> None:
    wr = WebhookResult(
        status="processed",
        event="push",
        triggers_fired=["t1", "t2"],
    )
    resp = _build_webhook_response(wr)
    assert resp["status"] == "processed"
    assert resp["event"] == "push"
    assert resp["triggers"] == [{"trigger_id": "t1"}, {"trigger_id": "t2"}]
    assert "deferred" not in resp


def test_build_webhook_response_without_triggers() -> None:
    wr = WebhookResult(status="processed", event="push")
    resp = _build_webhook_response(wr)
    assert resp == {"status": "processed", "event": "push"}


def test_build_webhook_response_with_deferred() -> None:
    wr = WebhookResult(
        status="processed",
        event="check_run",
        deferred=["d1"],
    )
    resp = _build_webhook_response(wr)
    assert resp["deferred"] == [{"trigger_id": "d1"}]
    assert "triggers" not in resp
