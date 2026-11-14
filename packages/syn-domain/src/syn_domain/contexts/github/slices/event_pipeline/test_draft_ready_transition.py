"""A failed check held back on a draft PR fires once the PR is marked ready (#2058).

Ingesting a check spends its dedup key before the evaluator holds it back, so
the same check can never be re-evaluated through the pipeline on its own. The
``ready_for_review`` transition re-checks the head SHA under a readiness-scoped
key. These tests drive the real Checks API synthesizer, ``EventPipeline`` and
dedup, with doubles only for GitHub: the Checks API and the draft lookup.
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
from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
from syn_shared.settings.polling import PollingSettings

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import InMemoryTriggerQueryStore
    from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA

pytestmark = pytest.mark.unit

_READY = PullRequestDraftReading(readiness=PullRequestReadiness.READY)
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
        )

    async def deliver(self, action: str) -> str:
        """Ingest a pull_request event and run the observer the pipeline would run."""
        event = _pr_event(action)
        result = await self.pipeline.ingest(event)
        if result.status == "processed":
            await self.service.on_pr_event(event)
        return result.status

    async def poll(self) -> None:
        await self.service._run_iteration()


@pytest.mark.asyncio
async def test_same_held_check_fires_once_after_ready_for_review() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)

    assert await rig.deliver("opened") == "processed"
    await rig.poll()
    assert rig.dispatches.fired == [], "a failed check on a draft PR must not dispatch"
    assert rig.draft_state.asked, "the draft state was never read"

    rig.draft_state.reading = _READY
    await rig.poll()
    assert rig.dispatches.fired == [], "the regular poll alone cannot re-evaluate the check"

    assert await rig.deliver("ready_for_review") == "processed"
    assert len(rig.dispatches.fired) == 1, "the held check must fire once the PR is ready"


@pytest.mark.asyncio
async def test_duplicate_ready_for_review_and_later_polls_do_not_fire_again() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.poll()
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
async def test_ready_for_review_while_lookup_still_says_draft_does_not_fire() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.poll()

    await rig.deliver("ready_for_review")
    assert rig.dispatches.fired == [], "the re-check goes through the same draft hold"


@pytest.mark.asyncio
async def test_rate_limited_recheck_does_not_fire() -> None:
    rig = _Rig(await draft._self_healing_store(), draft._DRAFT)
    await rig.deliver("opened")
    await rig.poll()
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
