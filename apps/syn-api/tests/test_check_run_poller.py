"""Tests for CheckRunPoller — poll-based self-healing (#602)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig
from syn_domain.contexts.github.services import (
    CheckRunIngestionService as CheckRunPoller,
)
from syn_domain.contexts.github.services import WebhookHealthTracker
from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
)
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)
from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline

if TYPE_CHECKING:
    from syn_domain.contexts.github.ports import ChecksAPIResult

# -- Test doubles ------------------------------------------------------------


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class InMemoryDedup:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def is_duplicate(self, dedup_key: str) -> bool:
        if dedup_key in self._seen:
            return True
        self._seen.add(dedup_key)
        return False

    async def mark_seen(self, dedup_key: str) -> None:
        self._seen.add(dedup_key)


class NullRepository:
    async def get_by_id(self, aggregate_id: str) -> None:
        return None

    async def save(self, aggregate: object) -> None:
        pass


class MockChecksClient:
    """In-memory implementation of ``GitHubChecksAPIPort`` for tests."""

    def __init__(self, check_runs: list[dict[str, Any]] | None = None) -> None:
        from syn_domain.contexts.github.ports import ChecksAPIResult

        runs = check_runs or []
        self._response = ChecksAPIResult(check_runs=runs, total_count=len(runs))
        self.poll_count = 0

    async def fetch_check_runs(
        self,
        owner: str,
        repo: str,
        ref: str,
        installation_id: str,
    ) -> ChecksAPIResult:
        self.poll_count += 1
        return self._response


class MockPollingSettings:
    poll_interval_seconds: float = 60.0
    safety_net_interval_seconds: float = 300.0
    webhook_stale_threshold_seconds: float = 1800.0
    dedup_ttl_seconds: int = 86400
    check_run_poll_interval_seconds: float = 30.0
    check_run_safety_interval_seconds: float = 120.0
    check_run_sha_ttl_seconds: int = 7200
    disabled: bool = False
    enabled: bool = True


class InMemoryPendingSHAStore:
    """Inline store for tests (avoids cross-package import issues)."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingSHA] = {}

    async def register(self, pending: PendingSHA) -> None:
        key = (pending.repository, pending.sha)
        if key not in self._pending:
            self._pending[key] = pending

    async def list_pending(self) -> list[PendingSHA]:
        return list(self._pending.values())

    async def remove(self, repository: str, sha: str) -> None:
        self._pending.pop((repository, sha), None)

    async def cleanup_stale(self, max_age: timedelta) -> int:
        return 0


async def _instant_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


async def _wait_for_poll_count(client: MockChecksClient, count: int, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while client.poll_count < count:
        if asyncio.get_event_loop().time() > deadline:
            msg = f"Timed out waiting for poll_count >= {count} (got {client.poll_count})"
            raise TimeoutError(msg)
        await asyncio.sleep(0)


async def _index_check_run_trigger(store: InMemoryTriggerQueryStore) -> None:
    """Index a self-healing trigger (check_run event) for test gating."""
    await store.index_trigger(
        trigger_id="t-1",
        name="self-healing",
        event="check_run.completed",
        repository="owner/repo",
        workflow_id="wf-1",
        conditions=[],
        input_mapping={},
        config=TriggerConfig(),
        installation_id="inst-1",
        created_by="test",
        status="active",
    )


def _make_pr_event(
    action: str = "synchronize",
    repository: str = "owner/repo",
    pr_number: int = 42,
    sha: str = "abc123",
    branch: str = "feat/test",
) -> NormalizedEvent:
    return NormalizedEvent(
        event_type="pull_request",
        action=action,
        repository=repository,
        installation_id="inst-1",
        dedup_key=f"pr:{repository}:{pr_number}:{action}:{sha}",
        source=EventSource.EVENTS_API,
        payload={
            "action": action,
            "number": pr_number,
            "pull_request": {
                "number": pr_number,
                "head": {"sha": sha, "ref": branch},
            },
            "repository": {"full_name": repository},
        },
        received_at=datetime.now(UTC),
    )


# -- Tests -------------------------------------------------------------------


class TestOnPrEvent:
    @pytest.mark.asyncio
    async def test_registers_sha_for_synchronize(self) -> None:
        sha_store = InMemoryPendingSHAStore()
        poller = CheckRunPoller(
            checks_api=MockChecksClient(),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                evaluator=EvaluateWebhookHandler(
                    store=InMemoryTriggerQueryStore(), repository=NullRepository()
                ),
            ),
            sha_store=sha_store,
            health_tracker=WebhookHealthTracker(),
            trigger_store=InMemoryTriggerQueryStore(),
            settings=MockPollingSettings(),
            sleep=_instant_sleep,
        )

        await poller.on_pr_event(_make_pr_event(action="synchronize", sha="abc123", pr_number=42))
        pending = await sha_store.list_pending()
        assert len(pending) == 1
        assert pending[0].sha == "abc123"
        assert pending[0].pr_number == 42

    @pytest.mark.asyncio
    async def test_registers_sha_for_opened(self) -> None:
        sha_store = InMemoryPendingSHAStore()
        poller = CheckRunPoller(
            checks_api=MockChecksClient(),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                evaluator=EvaluateWebhookHandler(
                    store=InMemoryTriggerQueryStore(), repository=NullRepository()
                ),
            ),
            sha_store=sha_store,
            health_tracker=WebhookHealthTracker(),
            trigger_store=InMemoryTriggerQueryStore(),
            settings=MockPollingSettings(),
            sleep=_instant_sleep,
        )

        await poller.on_pr_event(_make_pr_event(action="opened"))
        pending = await sha_store.list_pending()
        assert len(pending) == 1

    @pytest.mark.asyncio
    async def test_ignores_closed_action(self) -> None:
        sha_store = InMemoryPendingSHAStore()
        poller = CheckRunPoller(
            checks_api=MockChecksClient(),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                evaluator=EvaluateWebhookHandler(
                    store=InMemoryTriggerQueryStore(), repository=NullRepository()
                ),
            ),
            sha_store=sha_store,
            health_tracker=WebhookHealthTracker(),
            trigger_store=InMemoryTriggerQueryStore(),
            settings=MockPollingSettings(),
            sleep=_instant_sleep,
        )

        await poller.on_pr_event(_make_pr_event(action="closed"))
        pending = await sha_store.list_pending()
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_ignores_non_pr_events(self) -> None:
        sha_store = InMemoryPendingSHAStore()
        poller = CheckRunPoller(
            checks_api=MockChecksClient(),
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                evaluator=EvaluateWebhookHandler(
                    store=InMemoryTriggerQueryStore(), repository=NullRepository()
                ),
            ),
            sha_store=sha_store,
            health_tracker=WebhookHealthTracker(),
            trigger_store=InMemoryTriggerQueryStore(),
            settings=MockPollingSettings(),
            sleep=_instant_sleep,
        )

        push_event = NormalizedEvent(
            event_type="push",
            action="",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key="push:owner/repo:abc123",
            source=EventSource.EVENTS_API,
            payload={},
            received_at=datetime.now(UTC),
        )
        await poller.on_pr_event(push_event)
        pending = await sha_store.list_pending()
        assert len(pending) == 0


class TestPollLoop:
    @pytest.mark.asyncio
    async def test_polls_when_check_run_triggers_exist(self) -> None:
        store = InMemoryTriggerQueryStore()
        await _index_check_run_trigger(store)

        sha_store = InMemoryPendingSHAStore()
        await sha_store.register(
            PendingSHA(
                repository="owner/repo",
                sha="abc123",
                pr_number=42,
                branch="feat/test",
                installation_id="inst-1",
                registered_at=datetime.now(UTC),
            )
        )

        failed_check = {
            "id": 789,
            "name": "lint",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/owner/repo/runs/789",
            "output": {"title": "Lint failed", "summary": "2 errors"},
        }
        mock_client = MockChecksClient(check_runs=[failed_check])

        pipeline = EventPipeline(
            dedup=InMemoryDedup(),
            evaluator=EvaluateWebhookHandler(store=store, repository=NullRepository()),
        )

        poller = CheckRunPoller(
            checks_api=mock_client,
            pipeline=pipeline,
            sha_store=sha_store,
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=MockPollingSettings(),
            sleep=_instant_sleep,
        )

        await poller.start()
        await _wait_for_poll_count(mock_client, 1)
        await poller.stop()

        assert mock_client.poll_count >= 1
        # SHA should be removed after all checks completed
        remaining = await sha_store.list_pending()
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_skips_polling_when_no_check_run_triggers(self) -> None:
        """Poller should not call the Checks API when no check_run triggers exist."""
        store = InMemoryTriggerQueryStore()
        # Index a push trigger — NOT check_run
        await store.index_trigger(
            trigger_id="t-push",
            name="on-push",
            event="push",
            repository="owner/repo",
            workflow_id="wf-1",
            conditions=[],
            input_mapping={},
            config=TriggerConfig(),
            installation_id="inst-1",
            created_by="test",
            status="active",
        )

        sha_store = InMemoryPendingSHAStore()
        await sha_store.register(
            PendingSHA(
                repository="owner/repo",
                sha="abc123",
                pr_number=42,
                branch="feat/test",
                installation_id="inst-1",
                registered_at=datetime.now(UTC),
            )
        )

        mock_client = MockChecksClient()

        poller = CheckRunPoller(
            checks_api=mock_client,
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                evaluator=EvaluateWebhookHandler(store=store, repository=NullRepository()),
            ),
            sha_store=sha_store,
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=MockPollingSettings(),
            sleep=_instant_sleep,
        )

        await poller.start()
        # Let it run a couple iterations
        await asyncio.sleep(0.05)
        await poller.stop()

        # Should NOT have polled — no check_run triggers
        assert mock_client.poll_count == 0


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_stretches_poll_interval(self) -> None:
        """When the Checks API returns ``rate_limited=True``, the loop must
        sleep at least ``retry_after_seconds`` instead of its base interval.

        Otherwise the poller hot-loops back into the same 403.
        """
        from syn_domain.contexts.github.ports import ChecksAPIResult

        class RateLimitedChecksClient:
            def __init__(self) -> None:
                self.poll_count = 0

            async def fetch_check_runs(
                self,
                owner: str,
                repo: str,
                ref: str,
                installation_id: str,
            ) -> ChecksAPIResult:
                self.poll_count += 1
                return ChecksAPIResult(
                    check_runs=[],
                    total_count=0,
                    rate_limited=True,
                    retry_after_seconds=120.0,
                )

        store = InMemoryTriggerQueryStore()
        await _index_check_run_trigger(store)

        sha_store = InMemoryPendingSHAStore()
        await sha_store.register(
            PendingSHA(
                repository="owner/repo",
                sha="abc123",
                pr_number=42,
                branch="feat/test",
                installation_id="inst-1",
                registered_at=datetime.now(UTC),
            )
        )

        recorded_sleeps: list[float] = []

        async def _recording_sleep(seconds: float) -> None:
            recorded_sleeps.append(seconds)
            raise asyncio.CancelledError

        mock_client = RateLimitedChecksClient()
        poller = CheckRunPoller(
            checks_api=mock_client,
            pipeline=EventPipeline(
                dedup=InMemoryDedup(),
                evaluator=EvaluateWebhookHandler(store=store, repository=NullRepository()),
            ),
            sha_store=sha_store,
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=MockPollingSettings(),
            sleep=_recording_sleep,
        )

        await poller.start()
        assert poller._task is not None
        with contextlib.suppress(asyncio.CancelledError):
            await poller._task
        poller._task = None

        assert mock_client.poll_count == 1
        assert recorded_sleeps, "poll loop must reach the sleep step"
        assert recorded_sleeps[0] >= 120.0, (
            f"expected sleep >= 120s (rate-limit wait), got {recorded_sleeps[0]}"
        )


class TestDedup:
    @pytest.mark.asyncio
    async def test_webhook_and_poller_dedup(self) -> None:
        """Same check_run from webhook + poller should be deduplicated."""
        dedup = InMemoryDedup()
        store = InMemoryTriggerQueryStore()
        pipeline = EventPipeline(
            dedup=dedup,
            evaluator=EvaluateWebhookHandler(store=store, repository=NullRepository()),
        )

        # Simulate webhook delivering check_run.completed first
        webhook_event = NormalizedEvent(
            event_type="check_run",
            action="completed",
            repository="owner/repo",
            installation_id="inst-1",
            dedup_key="check_run:owner/repo:789:completed",
            source=EventSource.WEBHOOK,
            payload={
                "action": "completed",
                "check_run": {
                    "id": 789,
                    "name": "lint",
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "https://github.com/owner/repo/runs/789",
                    "output": {"title": "Lint failed", "summary": "2 errors"},
                    "pull_requests": [
                        {"number": 42, "head": {"ref": "feat/test", "sha": "abc123"}}
                    ],
                },
                "repository": {"full_name": "owner/repo"},
            },
            received_at=datetime.now(UTC),
            delivery_id="del-001",
        )
        result1 = await pipeline.ingest(webhook_event)
        assert result1.status == "processed"

        # Now poller synthesizes the same event
        from syn_domain.contexts.github.slices.event_pipeline.check_run_synthesizer import (
            synthesize_check_run_event,
        )

        pending = PendingSHA(
            repository="owner/repo",
            sha="abc123",
            pr_number=42,
            branch="feat/test",
            installation_id="inst-1",
            registered_at=datetime.now(UTC),
        )
        raw_check_run = {
            "id": 789,
            "name": "lint",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/owner/repo/runs/789",
            "output": {"title": "Lint failed", "summary": "2 errors"},
        }
        synthesized = synthesize_check_run_event(raw_check_run, pending)
        assert synthesized is not None

        # Same dedup key — should be deduplicated
        assert synthesized.dedup_key == webhook_event.dedup_key
        result2 = await pipeline.ingest(synthesized)
        assert result2.status == "deduplicated"
