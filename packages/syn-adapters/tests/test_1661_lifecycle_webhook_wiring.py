"""#1661: two settings turn the lifecycle webhook on in the registry production builds.

Built through the real ``create_coordinator_service()``, so a deleted
registration, a half-config that slips through, or a manager registered with
nothing configured each fails here. The configured case drives the registered
manager's live pass and checks what reached the wire: the URL from the setting,
signed with the secret from the setting, from the store the coordinator got.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from pydantic import ValidationError

from syn_adapters.execution_lifecycle import webhook_sink
from syn_adapters.execution_lifecycle.webhook_sink import SIGNATURE_HEADER
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.subscriptions import create_coordinator_service
from syn_domain.contexts.orchestration.slices.notify_execution_lifecycle import (
    ExecutionLifecycleNotice,
    ExecutionLifecycleNoticeProcessManager,
    ExecutionOutcome,
    LifecycleNoticeRecord,
)
from syn_shared.settings.lifecycle_webhook import (
    ENV_SYN_LIFECYCLE_WEBHOOK_SECRET,
    ENV_SYN_LIFECYCLE_WEBHOOK_URL,
)

pytestmark = pytest.mark.unit

_URL = "https://hooks.example.com/syn/lifecycle?tenant=t-7"
_SECRET = "whsec-0f3a-not-a-real-key"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, raising=False)
    monkeypatch.delenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, raising=False)


def _managers(store: InMemoryProjectionStore) -> list[ExecutionLifecycleNoticeProcessManager]:
    service = create_coordinator_service(
        event_store=cast("Any", object()), projection_store=cast("Any", store)
    )
    return [
        p for p in service._projections if isinstance(p, ExecutionLifecycleNoticeProcessManager)
    ]


def test_unconfigured_registers_no_manager_and_says_so_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        assert _managers(InMemoryProjectionStore()) == []
    off = [r for r in caplog.records if "lifecycle webhook is off" in r.getMessage()]
    assert len(off) == 1


@pytest.mark.parametrize(
    ("present", "missing"),
    [
        (ENV_SYN_LIFECYCLE_WEBHOOK_URL, ENV_SYN_LIFECYCLE_WEBHOOK_SECRET),
        (ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, ENV_SYN_LIFECYCLE_WEBHOOK_URL),
    ],
)
def test_half_configured_refuses_to_build_the_registry(
    monkeypatch: pytest.MonkeyPatch, present: str, missing: str
) -> None:
    monkeypatch.setenv(present, _URL if present == ENV_SYN_LIFECYCLE_WEBHOOK_URL else _SECRET)
    with pytest.raises(ValidationError, match=f"{missing} is not"):
        _managers(InMemoryProjectionStore())


async def test_configured_registers_one_manager_that_posts_signed_to_the_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_URL, _URL)
    monkeypatch.setenv(ENV_SYN_LIFECYCLE_WEBHOOK_SECRET, _SECRET)
    sent: list[httpx.Request] = []

    def receiver(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(204)

    real_client = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:  # noqa: ANN401 - forwards httpx's own kwargs
        return real_client(transport=httpx.MockTransport(receiver), **kwargs)

    # The sink builds its own client when none is injected, as production's is.
    monkeypatch.setattr(webhook_sink.httpx, "AsyncClient", client)

    store = InMemoryProjectionStore()
    with caplog.at_level(logging.INFO):
        (manager,) = _managers(store)
    record = LifecycleNoticeRecord(
        notice=ExecutionLifecycleNotice(
            execution_id="exec-1661",
            workflow_id="wf-7",
            outcome=ExecutionOutcome.COMPLETED,
            occurred_at=datetime(2026, 11, 27, 7, 0, tzinfo=UTC),
        )
    )
    # Owed in the store the factory was given: the durable to-do list.
    await store.save(manager.PROJECTION_NAME, record.key, record.model_dump(mode="json"))

    assert await manager.process_pending() == 1

    (request,) = sent
    assert str(request.url) == _URL
    expected = hmac.new(_SECRET.encode(), request.content, hashlib.sha256).hexdigest()
    assert request.headers[SIGNATURE_HEADER] == f"sha256={expected}"
    # The startup line names the host only. (httpx's own request log is not ours.)
    startup = [r.getMessage() for r in caplog.records if "lifecycle webhook" in r.getMessage()]
    assert startup == [
        "Execution lifecycle webhook is on, posting signed notices to hooks.example.com"
    ]
    assert all(_SECRET not in r.getMessage() for r in caplog.records)
