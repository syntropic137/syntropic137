"""WebhookExecutionLifecycleSink: signed, keyed, and raising whenever it was not acknowledged (#1661).

Every response comes from ``httpx.MockTransport``; no test reaches the network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from syn_adapters.execution_lifecycle import (
    IDEMPOTENCY_KEY_HEADER,
    SIGNATURE_HEADER,
    LifecycleNoticeUndeliveredError,
    WebhookExecutionLifecycleSink,
)
from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
    ExecutionLifecycleNotice,
    ExecutionOutcome,
)

pytestmark = pytest.mark.unit

_URL = "https://receiver.example/hooks/lifecycle"
_SECRET = "s3cret-lifecycle-key-0xA7"
_NOTICE = ExecutionLifecycleNotice(
    execution_id="exec-4711",
    workflow_id="wf-9",
    outcome=ExecutionOutcome.CANCELLED,
    occurred_at=datetime(2026, 11, 18, 9, 30, tzinfo=UTC),
    cancel_reason="operator stopped it",
)


def _sink(
    handler: httpx.MockTransport, secret: str = _SECRET
) -> tuple[WebhookExecutionLifecycleSink, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler)
    return WebhookExecutionLifecycleSink(_URL, SecretStr(secret), client=client), client


def _capturing(status: int = 200) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    return httpx.MockTransport(handle), seen


async def test_posts_the_notice_keyed_and_signed_over_the_received_bytes() -> None:
    transport, seen = _capturing()
    sink, client = _sink(transport)
    async with client:
        await sink.deliver(_NOTICE)

    [request] = seen
    received = request.content
    assert request.method == "POST"
    assert str(request.url) == _URL
    assert json.loads(received) == _NOTICE.model_dump(mode="json")
    assert request.headers[IDEMPOTENCY_KEY_HEADER] == "exec-4711:cancelled"
    expected = "sha256=" + hmac.new(_SECRET.encode(), received, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(request.headers[SIGNATURE_HEADER], expected)


async def test_a_different_secret_gives_a_different_signature() -> None:
    transport, seen = _capturing()
    first, first_client = _sink(transport)
    second, second_client = _sink(transport, secret="another-secret-entirely")
    async with first_client, second_client:
        await first.deliver(_NOTICE)
        await second.deliver(_NOTICE)

    assert seen[0].content == seen[1].content
    assert seen[0].headers[SIGNATURE_HEADER] != seen[1].headers[SIGNATURE_HEADER]


@pytest.mark.parametrize("status", [200, 204])
async def test_a_2xx_is_delivered(status: int) -> None:
    transport, seen = _capturing(status)
    sink, client = _sink(transport)
    async with client:
        await sink.deliver(_NOTICE)
    assert len(seen) == 1


@pytest.mark.parametrize("status", [500, 404])
async def test_a_non_2xx_leaves_the_notice_owed(status: int) -> None:
    transport, seen = _capturing(status)
    sink, client = _sink(transport)
    async with client:
        with pytest.raises(LifecycleNoticeUndeliveredError, match=f"HTTP {status}"):
            await sink.deliver(_NOTICE)
    # No retry loop inside the adapter: the process manager's next pass retries.
    assert len(seen) == 1


@pytest.mark.parametrize("status", [302, 307, 308])
async def test_a_redirect_is_not_followed_even_by_a_client_that_would(status: int) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "other.example":
            return httpx.Response(200)
        return httpx.Response(status, headers={"Location": "https://other.example/redirected"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True)
    sink = WebhookExecutionLifecycleSink(_URL, SecretStr(_SECRET), client=client)
    async with client:
        with pytest.raises(LifecycleNoticeUndeliveredError, match=f"HTTP {status}"):
            await sink.deliver(_NOTICE)
    # The signed body went to the configured receiver only, never the redirect target.
    assert [str(request.url) for request in seen] == [_URL]


@pytest.mark.parametrize(
    "fault",
    [httpx.ReadTimeout("timed out"), httpx.ConnectError("connection refused")],
    ids=["timeout", "connect-error"],
)
async def test_a_transport_fault_leaves_the_notice_owed(fault: httpx.RequestError) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise fault

    sink, client = _sink(httpx.MockTransport(handle))
    async with client:
        with pytest.raises(LifecycleNoticeUndeliveredError) as raised:
            await sink.deliver(_NOTICE)
    assert raised.value.__cause__ is fault


async def test_neither_the_secret_nor_the_signature_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport, seen = _capturing(500)
    sink, client = _sink(transport)
    caplog.set_level(logging.DEBUG)
    async with client:
        with pytest.raises(LifecycleNoticeUndeliveredError) as raised:
            await sink.deliver(_NOTICE)
        # The process manager logs the failure with its traceback; do the same.
        logging.getLogger("test").exception("undelivered", exc_info=raised.value)

    signature = seen[0].headers[SIGNATURE_HEADER]
    logged = caplog.text + "".join(str(record.args) for record in caplog.records)
    assert caplog.records
    assert _SECRET not in logged
    assert signature.removeprefix("sha256=") not in logged


def test_refuses_to_construct_without_a_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        WebhookExecutionLifecycleSink(_URL, SecretStr(""))
