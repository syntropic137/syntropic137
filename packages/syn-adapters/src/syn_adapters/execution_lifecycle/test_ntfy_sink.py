"""NtfyExecutionLifecycleSink: one publish per notice, shaped by outcome, raising whenever unacknowledged (#1661).

Every response comes from ``httpx.MockTransport``; no test reaches the network.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from syn_adapters.execution_lifecycle import (
    SEQUENCE_ID_HEADER,
    LifecycleNoticeUndeliveredError,
    NtfyExecutionLifecycleSink,
)
from syn_adapters.execution_lifecycle.ntfy_sink import MAX_MESSAGE_BYTES
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.lifecycle_events import (
    cancelled_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle.value_objects import (
    ExecutionLifecycleNotice,
    ExecutionOutcome,
    lifecycle_notice,
)

pytestmark = pytest.mark.unit

_URL = "https://ntfy.example/syn-lifecycle"
_TOKEN = "tk_n7fyAccessToken0xB3"
_WHEN = datetime(2026, 11, 18, 9, 30, tzinfo=UTC)
_FAILED = ExecutionLifecycleNotice(
    execution_id="exec-4711",
    workflow_id="wf-9",
    outcome=ExecutionOutcome.FAILED,
    occurred_at=_WHEN,
    failure_classification=FailureClassification.PLATFORM,
    error_message="workspace vanished",
)
_COMPLETED = ExecutionLifecycleNotice(
    execution_id="exec-4712",
    workflow_id="wf-9",
    outcome=ExecutionOutcome.COMPLETED,
    occurred_at=_WHEN,
)
_CANCELLED = ExecutionLifecycleNotice(
    execution_id="exec-4713",
    workflow_id="wf-9",
    outcome=ExecutionOutcome.CANCELLED,
    occurred_at=_WHEN,
    cancel_reason="operator stopped it",
)


def _capturing(status: int = 200) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    return httpx.MockTransport(handle), seen


async def _publish(
    notice: ExecutionLifecycleNotice, token: SecretStr | None = None
) -> httpx.Request:
    transport, seen = _capturing()
    async with httpx.AsyncClient(transport=transport) as client:
        await NtfyExecutionLifecycleSink(_URL, token=token, client=client).deliver(notice)
    [request] = seen
    return request


@pytest.mark.parametrize(
    ("notice", "body", "tags", "priority"),
    [
        (_FAILED, "exec-4711 failed (wf-9): platform", "x", "4"),
        (_COMPLETED, "exec-4712 completed (wf-9)", "white_check_mark", "3"),
        (_CANCELLED, "exec-4713 cancelled (wf-9): operator stopped it", "no_entry_sign", "3"),
    ],
    ids=["failed", "completed", "cancelled"],
)
async def test_publishes_one_line_shaped_by_the_outcome(
    notice: ExecutionLifecycleNotice, body: str, tags: str, priority: str
) -> None:
    request = await _publish(notice)

    assert request.method == "POST"
    assert str(request.url) == _URL
    assert request.content.decode() == body
    assert request.headers["Title"] == f"Execution {notice.outcome}"
    assert request.headers["Tags"] == tags
    assert request.headers["Priority"] == priority


@pytest.mark.parametrize(
    ("reason", "body"),
    [
        (
            "operator stopped it\r\n\tmaintenance  window",
            "exec-4714 cancelled (wf-9): operator stopped it maintenance window",
        ),
        ("停" * 2000, None),
    ],
    ids=["multiline", "long-multibyte"],
)
async def test_a_cancel_reason_from_the_api_still_publishes_one_short_line(
    reason: str, body: str | None
) -> None:
    # CancelRequest.reason is unbounded free text, carried unchanged to the notice.
    notice = lifecycle_notice(
        cancelled_event(CancelExecutionCommand("exec-4714", "p-1", reason), "wf-9")
    )
    assert notice is not None

    content = (await _publish(notice)).content
    text = content.decode()  # raises if the cut split a character

    assert len(content) <= MAX_MESSAGE_BYTES
    assert text.splitlines() == [text]
    assert text.startswith("exec-4714 cancelled (wf-9): ")
    if body is None:
        assert text.endswith("停…")
    else:
        assert text == body


async def test_the_sequence_id_is_stable_per_key_and_one_ntfy_accepts() -> None:
    first, again = await _publish(_FAILED), await _publish(_FAILED)
    other = await _publish(_COMPLETED)

    sequence_id = first.headers[SEQUENCE_ID_HEADER]
    assert sequence_id == hashlib.sha256(b"exec-4711:failed").hexdigest()
    assert again.headers[SEQUENCE_ID_HEADER] == sequence_id
    assert other.headers[SEQUENCE_ID_HEADER] != sequence_id
    # ntfy's sequenceIDRegex: anything else is refused with HTTP 400.
    assert re.fullmatch(r"[-_A-Za-z0-9]{1,64}", sequence_id)


async def test_the_token_is_sent_as_a_bearer_only_when_given() -> None:
    with_token = await _publish(_FAILED, token=SecretStr(_TOKEN))
    without = await _publish(_FAILED)

    assert with_token.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert "Authorization" not in without.headers


def test_the_token_is_absent_from_repr() -> None:
    sink = NtfyExecutionLifecycleSink(_URL, token=SecretStr(_TOKEN))
    assert _TOKEN not in repr(sink)
    assert _TOKEN not in repr(vars(sink))


@pytest.mark.parametrize("status", [500, 404, 403, 302])
async def test_a_non_2xx_leaves_the_notice_owed(status: int) -> None:
    transport, seen = _capturing(status)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        sink = NtfyExecutionLifecycleSink(_URL, client=client)
        with pytest.raises(LifecycleNoticeUndeliveredError, match=f"HTTP {status}"):
            await sink.deliver(_FAILED)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "fault",
    [httpx.ReadTimeout("timed out"), httpx.ConnectError("connection refused")],
    ids=["timeout", "connect-error"],
)
async def test_a_transport_fault_leaves_the_notice_owed(fault: httpx.RequestError) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise fault

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sink = NtfyExecutionLifecycleSink(_URL, client=client)
        with pytest.raises(LifecycleNoticeUndeliveredError) as raised:
            await sink.deliver(_FAILED)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


async def test_a_transport_fault_that_echoes_the_token_leaks_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError(f"reset after {request.headers['Authorization']}", request=request)

    caplog.set_level(logging.DEBUG)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sink = NtfyExecutionLifecycleSink(_URL, token=SecretStr(_TOKEN), client=client)
        with pytest.raises(LifecycleNoticeUndeliveredError) as raised:
            await sink.deliver(_FAILED)
        logging.getLogger("test").exception("undelivered", exc_info=raised.value)

    assert caplog.records
    assert _TOKEN not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "ntfy.sh/topic",
        "ftp://ntfy.sh/topic",
        "https://",
        "http://:80/topic",
        "https://ntfy.sh:abc/topic",
    ],
)
def test_refuses_a_url_that_is_not_http(url: str) -> None:
    with pytest.raises(ValueError, match="http"):
        NtfyExecutionLifecycleSink(url)
