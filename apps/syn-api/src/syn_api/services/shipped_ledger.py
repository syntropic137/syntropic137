"""The shipped ledger's API-side duties: merges in, the backfill, the read service.

Three things the API process does for ``GET /metrics/shipped``:

1. **Records merges.** A pipeline observer turns each ``pull_request`` event
   with action ``closed`` and the PR merged (``merged: true`` or a
   ``merged_at``) into ``ShippedLedger.record_pull_request_merged``. Both
   sources that feed the pipeline reach it: webhooks and the Events API
   poller. Like every pipeline observer it never sees a deduplicated event or
   a cold-start replay (ADR-060 s9). The write is idempotent by
   ``(repository, number)``, so a redelivery the fail-open dedup lets through
   changes nothing. Every merge is kept; only merges of PRs a run created are
   counted.
2. **Backfills once.** On start, the ledger is rebuilt from the Lane 2
   history if this ledger version has not been (see
   ``syn_adapters.events.shipped_ledger.backfill`` for what it reads and
   costs). In the background: the API serves while it runs.
3. **Serves the read.** One ``ShippedMetricsQueryService`` per process, so
   its cache and request coalescing are shared by every request.

Best-effort throughout: a failure is logged, never raised into the pipeline
or the startup.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration import (
    ExecutionAttribution,
    ExecutionListReads,
    PullRequestMerged,
    ShippedMetricsQueryService,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.contexts.github import NormalizedEvent

logger = logging.getLogger(__name__)

_PULL_REQUEST = "pull_request"
_CLOSED = "closed"


@dataclass(frozen=True)
class PullRequestMerge:
    """The merge one ``pull_request`` event reports."""

    repository: str
    number: int
    merged_at: datetime

    @classmethod
    def from_event(cls, event: NormalizedEvent) -> PullRequestMerge | None:
        """The merge in ``event``, or None when it does not report one."""
        if event.event_type != _PULL_REQUEST or event.action != _CLOSED:
            return None
        number = _merged_number(event)
        if number is None:
            return None
        return cls(repository=event.repository, number=number, merged_at=_merged_at(event))


def _merged_number(event: NormalizedEvent) -> int | None:
    """The PR number when the event's PR was merged in a named repo, else None."""
    pr = event.payload.get("pull_request") or {}
    if not (pr.get("merged") is True or pr.get("merged_at")) or not event.repository:
        return None
    number = event.payload.get("number") or pr.get("number")
    return number if isinstance(number, int) and number > 0 else None


def _merged_at(event: NormalizedEvent) -> datetime:
    """``merged_at`` as an instant; when it is missing or unreadable, receipt."""
    raw = (event.payload.get("pull_request") or {}).get("merged_at")
    if not raw:
        return event.received_at
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return event.received_at


async def record_pull_request_merge(event: NormalizedEvent) -> None:
    """Pipeline observer: record the merge ``event`` reports, if it reports one."""
    merge = PullRequestMerge.from_event(event)
    if merge is None:
        return
    from syn_api._wiring import get_event_store_instance

    store = get_event_store_instance()
    await store.initialize()
    await store.shipped_ledger.record_pull_request_merged(
        PullRequestMerged(
            repository=merge.repository, number=merge.number, merged_at=merge.merged_at
        )
    )
    logger.info("Recorded PR merge %s#%d", merge.repository, merge.number)


_registered: set[int] = set()
_service: ShippedMetricsQueryService | None = None
_backfill_task: asyncio.Task[None] | None = None


def shipped_metrics_service() -> ShippedMetricsQueryService:
    """The process's one read service (its cache and coalescing are shared)."""
    global _service
    if _service is None:
        from syn_api._wiring import get_event_store_instance

        _service = ShippedMetricsQueryService(get_event_store_instance().shipped_ledger)
    return _service


def start_shipped_ledger() -> None:
    """Register the merge recorder and start the one-time backfill. Never raises."""
    global _backfill_task
    from syn_api._wiring import get_event_pipeline

    try:
        pipeline = get_event_pipeline()
        if id(pipeline) not in _registered:
            pipeline.add_observer(record_pull_request_merge)
            _registered.add(id(pipeline))
    except Exception:
        logger.warning("PR merge recorder not registered; merges will not be counted.")
    if _backfill_task is None:
        _backfill_task = asyncio.get_running_loop().create_task(
            _run_backfill(), name="shipped-ledger-backfill"
        )


async def _run_backfill() -> None:
    from syn_adapters.events.shipped_ledger import backfill
    from syn_api._wiring import get_event_store_instance, get_projection_mgr

    try:
        store = get_event_store_instance()
        await store.initialize()
        if store.pool is None:
            return
        reads = ExecutionListReads(get_projection_mgr().store)

        async def attributions(ids: Sequence[str]) -> Mapping[str, ExecutionAttribution]:
            rows = await reads.by_ids(ids)
            return {
                key: ExecutionAttribution(
                    execution_id=key,
                    workflow_id=row.workflow_id,
                    workflow_name=row.workflow_name,
                    repositories=_slugs(row.repos),
                )
                for key, row in rows.items()
            }

        await backfill(store.pool, store.shipped_ledger, attributions)
    except Exception:
        logger.warning(
            "Shipped ledger backfill failed; it will be retried on the next start", exc_info=True
        )


def _slugs(repos: Sequence[str]) -> tuple[str, ...]:
    slugs: list[str] = []
    for value in repos:
        try:
            slugs.append(RepositoryRef.parse(value).slug)
        except ValueError:
            continue
    return tuple(slugs)
