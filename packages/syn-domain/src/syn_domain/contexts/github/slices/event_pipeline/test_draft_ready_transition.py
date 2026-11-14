"""A failed check held back on a draft PR fires once the PR is marked ready (#2058).

Two producers, two paths. The Checks API poll does not ingest a completed check
while its PR is a draft (or unknown), so the key stays unspent and the SHA
pending, and the first poll that reads READY ingests it: this is the only path a
poll-only install has, because the Events API never emits ``ready_for_review``.
A webhook ``check_run`` spends its key while the PR is a draft, so the
``ready_for_review`` webhook re-checks it under a readiness-scoped key. These
tests drive the real Checks API synthesizer, ``EventPipeline`` and dedup, with
doubles only for GitHub: the Checks API and the draft lookup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.github.ports import (
    ChecksAPIResult,
    PullRequestDraftReading,
    PullRequestReadiness,
)
from syn_domain.contexts.github.services.check_run_ingestion import CheckRunIngestionService
from syn_domain.contexts.github.services.webhook_health import WebhookHealthTracker
from syn_domain.contexts.github.slices.evaluate_webhook import test_draft_pull_request as draft
from syn_domain.contexts.github.slices.event_pipeline.check_run_synthesizer import (
    synthesize_check_run_event,
)
from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)
from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
from syn_shared.settings.polling import PollingSettings

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore

pytestmark = pytest.mark.unit

_READY = PullRequestDraftReading(readiness=PullRequestReadiness.READY)
_UNKNOWN = PullRequestDraftReading(readiness=PullRequestReadiness.UNKNOWN, detail="HTTP 502")
_FAILED_CHECK = {
    "id": 2058001,
    "name": "lint",
    "status": "completed",
    "conclusion": "failure",
    "html_url": "https://github.com/acme/widgets/runs/2058001",
    "output": {"title": "lint failed", "summary": "E501"},
}


class _SeenKeys:
    """Atomic check-and-mark dedup, as ``DedupPort`` requires."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def is_duplicate(self, dedup_key: str) -> bool:
        if dedup_key in self._seen:
            return True
        self._seen.add(dedup_key)
        return False

    async def mark_seen(self, dedup_key: str) -> None:
        self._seen.add(dedup_key)


class _ChecksAPI:
    """``GitHubChecksAPIPort`` double: one failed, completed check on the head SHA."""

    def __init__(self) -> None:
        self.fetched: list[str] = []
        self.rate_limited = False

    async def fetch_check_runs(
        self, owner: str, repo: str, ref: str, installation_id: str
    ) -> ChecksAPIResult:
        del owner, repo, installation_id
        self.fetched.append(ref)
        if self.rate_limited:
            return ChecksAPIResult(
                check_runs=[], total_count=0, rate_limited=True, retry_after_seconds=60
            )
        return ChecksAPIResult(check_runs=[dict(_FAILED_CHECK)], total_count=1)


class _PendingSHAs:
    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingSHA] = {}

    async def register(self, pending: PendingSHA) -> None:
        self._pending.setdefault((pending.repository, pending.sha), pending)

    async def list_pending(self) -> list[PendingSHA]:
        return list(self._pending.values())

    async def remove(self, repository: str, sha: str) -> None:
        self._pending.pop((repository, sha), None)

    async def cleanup_stale(self, max_age: timedelta) -> int:
        del max_age
        return 0


def _pr_event(action: str) -> NormalizedEvent:
    payload = {
        "action": action,
        "number": draft._PR,
        "pull_request": {
            "number": draft._PR,
            "head": {"sha": draft._HEAD_SHA, "ref": "feat/x"},
        },
        "repository": {"full_name": draft._REPO},
    }
    return NormalizedEvent(
        event_type="pull_request",
        action=action,
        repository=draft._REPO,
        installation_id="inst-1",
        dedup_key=compute_dedup_key("pull_request", action, payload),
        source=EventSource.WEBHOOK,
        payload=payload,
        received_at=datetime.now(UTC),
    )


class _Rig:
    """The production path from a PR event to a dispatch, GitHub stubbed out."""

    def __init__(self, store: InMemoryTriggerQueryStore, reading: PullRequestDraftReading) -> None:
        self.draft_state = draft._DraftState(reading)
        self.dispatches = draft._Dispatches()
        self.checks_api = _ChecksAPI()
        self.pipeline = EventPipeline(
            _SeenKeys(), draft._handler(store, self.draft_state, self.dispatches)
        )
        self.service = CheckRunIngestionService(
            checks_api=self.checks_api,
            pipeline=self.pipeline,
            sha_store=_PendingSHAs(),
            health_tracker=WebhookHealthTracker(),
            trigger_store=store,
            settings=PollingSettings(),
            draft_state=self.draft_state,
        )
        self.sha_store = self.service._sha_store

    async def deliver(self, action: str) -> str:
        """Ingest a pull_request event and run the observer the pipeline would run."""
        event = _pr_event(action)
        result = await self.pipeline.ingest(event)
        if result.status == "processed":
            await self.service.on_pr_event(event)
        return result.status

    async def poll(self) -> None:
        await self.service._run_iteration()

    async def check_run_webhook_while_draft(self) -> None:
        """The failed check arrives by webhook: its key is spent on a held evaluation."""
        pending = PendingSHA(
            repository=draft._REPO,
            sha=draft._HEAD_SHA,
            pr_number=draft._PR,
            branch="feat/x",
            installation_id="inst-1",
            registered_at=datetime.now(UTC),
        )
        event = synthesize_check_run_event(dict(_FAILED_CHECK), pending)
        assert event is not None
        assert (await self.pipeline.ingest(event)).status == "processed"


@pytest.mark.asyncio
async def test_poll_only_held_check_fires_once_after_the_pr_turns_ready() -> None:
    """No ready_for_review is delivered: the Events API never emits one."""
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)

    assert await rig.deliver("opened") == "processed"
    await rig.poll()
    await rig.poll()
    assert rig.dispatches.fired == [], "a failed check on a draft PR must not dispatch"
    assert rig.draft_state.asked, "the draft state was never read"
    assert await rig.sha_store.list_pending(), "the held SHA must stay pending"

    rig.draft_state.reading = _READY
    await rig.poll()
    assert len(rig.dispatches.fired) == 1, "the held check must fire once the PR is ready"

    await rig.poll()
    await rig.poll()
    assert len(rig.dispatches.fired) == 1
    assert await rig.sha_store.list_pending() == []


@pytest.mark.asyncio
async def test_unknown_draft_state_holds_the_check_until_it_reads_ready(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _Rig(await draft._self_healing_store(), _UNKNOWN)
    await rig.deliver("opened")

    with caplog.at_level("INFO"):
        await rig.poll()
    assert rig.dispatches.fired == [], "an unknown draft state must not dispatch"
    assert "is unknown (HTTP 502); kept pending" in caplog.text

    rig.draft_state.reading = _READY
    await rig.poll()
    assert len(rig.dispatches.fired) == 1


@pytest.mark.asyncio
async def test_check_spent_by_webhook_while_draft_fires_once_after_ready_for_review() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.check_run_webhook_while_draft()
    await rig.poll()
    assert rig.dispatches.fired == []

    rig.draft_state.reading = _READY
    await rig.poll()
    assert rig.dispatches.fired == [], "the spent key is deduplicated on the poll"

    assert await rig.deliver("ready_for_review") == "processed"
    assert len(rig.dispatches.fired) == 1, "the held check must fire once the PR is ready"
    await rig.poll()
    assert len(rig.dispatches.fired) == 1


@pytest.mark.asyncio
async def test_duplicate_ready_for_review_and_later_polls_do_not_fire_again() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.check_run_webhook_while_draft()
    rig.draft_state.reading = _READY
    await rig.deliver("ready_for_review")
    assert len(rig.dispatches.fired) == 1

    # The same transition from a second source is deduplicated by the pipeline.
    assert await rig.deliver("ready_for_review") == "deduplicated"
    # Even if the re-check itself ran again, its readiness-scoped key is spent.
    await rig.service.on_pr_event(_pr_event("ready_for_review"))
    await rig.poll()
    assert len(rig.dispatches.fired) == 1


@pytest.mark.asyncio
async def test_ready_for_review_then_poll_fires_once_for_a_poll_held_check() -> None:
    """The check was held by the poll (key unspent), then ready_for_review arrives."""
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.poll()
    rig.draft_state.reading = _READY

    await rig.deliver("ready_for_review")
    assert len(rig.dispatches.fired) == 1
    await rig.poll()
    assert len(rig.dispatches.fired) == 1


@pytest.mark.asyncio
async def test_ready_for_review_while_lookup_still_says_draft_waits_for_the_poll() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.check_run_webhook_while_draft()

    await rig.deliver("ready_for_review")
    assert rig.dispatches.fired == [], "the re-check goes through the same draft hold"


@pytest.mark.asyncio
async def test_rate_limited_recheck_does_not_fire() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.check_run_webhook_while_draft()
    rig.draft_state.reading = _READY
    rig.checks_api.rate_limited = True

    await rig.deliver("ready_for_review")
    assert rig.dispatches.fired == []


@pytest.mark.asyncio
async def test_ready_pr_fires_once_from_the_regular_poll() -> None:
    rig = _Rig(await draft._self_healing_store(), _READY)
    await rig.deliver("opened")
    await rig.poll()
    await rig.poll()
    assert len(rig.dispatches.fired) == 1
