"""Quarantine Notice ProcessManager (#1547, ADR-025).

Subscribes to `WorkflowFailed` and tells the PR the failed run was working on
that its unpushed work is on a quarantine ref, using the Processor To-Do List
pattern.

PROJECTION SIDE (handle_event): writes one notice per (execution, phase,
  repository) the event says landed on a quarantine ref. Pure, replay-safe: a
  replayed event whose facts the store already holds writes nothing, so a
  posted notice stays posted.

PROCESSOR SIDE (process_pending): posts or edits the comment. Called ONLY for
  live events, never during catch-up replay. A notice with no PR yet asks the
  forge on every pass and posts once one is open from the branch; the
  platform's clock tick guarantees a pass comes.

Zero business logic: what landed where is decided by the failure event, and
what the comment says by `QuarantineNotice`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from event_sourcing import (
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    ProcessManager,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
    ProjectionStore,
)

from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.notify_quarantine.value_objects import (
    OWED_STATUSES,
    QuarantineNotice,
    read_notice,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports.RemoteBranchPort import RemoteBranchPort

logger = logging.getLogger(__name__)

_WORKFLOW_FAILED = "WorkflowFailed"

#: Every event that can mean a PR has since been opened from a branch a notice
#: is waiting on: a later phase, a resume, a run finishing. Subscribed for the
#: coordinator to run the processor side, which asks the forge again.
#:
#: None of those is guaranteed to follow a failure: a PR opened by hand on a
#: quiet system arrives as no event at all. So the platform's durable clock is
#: subscribed too - the recovery clock appends one `InventoryReconciliationSweep`
#: per interval to the event store - and is the wake that does not depend on
#: anything else happening. Named by string: a tick carries no data this reads.
_CLOCK_TICK = "InventoryReconciliationSweep"
_RECHECK_EVENTS = {
    "PhaseStarted",
    "PhaseCompleted",
    "WorkflowCompleted",
    "ExecutionResumed",
    _CLOCK_TICK,
}


class PullRequestCommenter(Protocol):
    """Posts a comment on a PR, or edits the one already carrying ``marker``.

    Host-side: the platform's own forge credential, never a workspace's.
    Returns the comment's id. Raises when the forge refused or could not be
    reached; the notice stays owed and is offered again.
    """

    async def upsert_comment(
        self,
        repository: str,
        pull_request: int,
        *,
        marker: str,
        body: str,
        comment_id: int | None,
    ) -> int: ...


class QuarantineNoticeProcessManager(ProcessManager):
    """Tells a PR its run's work is on a quarantine ref."""

    PROJECTION_NAME = "quarantine_notice"
    VERSION = 1

    def __init__(
        self,
        commenter: PullRequestCommenter | None = None,
        store: ProjectionStore | None = None,
        branches: RemoteBranchPort | None = None,
    ) -> None:
        self._commenter = commenter
        self._store = store
        self._branches = branches

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return {_WORKFLOW_FAILED, *_RECHECK_EVENTS}

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        """PROJECTION SIDE: record each landed quarantine as owed. No side effects."""
        event_type = envelope.metadata.event_type or "Unknown"
        try:
            if isinstance(envelope.event, WorkflowFailedEvent):
                await self._record(envelope.event)
            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=envelope.metadata.global_nonce or 0,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS
        except Exception:
            logger.exception(
                "Error in quarantine notice process manager", extra={"type": event_type}
            )
            return ProjectionResult.FAILURE

    async def _record(self, event: WorkflowFailedEvent) -> None:
        """Write a notice per landed ref, unless the store already holds its facts.

        Same facts: nothing is written, which is what keeps a replay from
        reopening a posted notice. Different facts for the same key - the
        phase ran again and quarantined again - reopen it with its
        `comment_id` kept, so the processor edits that comment rather than
        adding a second.
        """
        if self._store is None or not event.failed_phase_id:
            return
        for quarantined in event.quarantined_refs:
            notice = QuarantineNotice(
                execution_id=event.execution_id,
                phase_id=event.failed_phase_id,
                failed_at=event.failed_at,
                quarantined=quarantined,
            )
            row = await self._store.get(self.PROJECTION_NAME, notice.key)
            current = read_notice(row) if row is not None else None
            if current is not None:
                if current.quarantined == quarantined:
                    continue
                notice = notice.model_copy(
                    update={"comment_id": current.comment_id, "pull_request": None}
                )
            await self._save(notice)

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: post or edit each owed comment. Live-only, idempotent."""
        if self._store is None or self._commenter is None:
            return 0
        posted = 0
        for status in OWED_STATUSES:
            for row in await self._store.query(self.PROJECTION_NAME, filters={"status": status}):
                notice = read_notice(row)
                if notice is None:
                    continue
                if await self._post(notice):
                    posted += 1
        return posted

    async def _pull_request(self, notice: QuarantineNotice) -> int | None:
        """The PR to tell: the one open at failure, else whatever is open now."""
        q = notice.quarantined
        if q.pull_request is not None:
            return q.pull_request
        if self._branches is None or "/" not in q.repository:
            return None
        reading = await self._branches.read_branch(q.repository, q.branch)
        return reading.open_pull_request

    async def _post(self, notice: QuarantineNotice) -> bool:
        assert self._commenter is not None
        try:
            pull_request = await self._pull_request(notice)
            if pull_request is None:
                if notice.status != "awaiting_pr":
                    await self._save(notice.model_copy(update={"status": "awaiting_pr"}))
                return False
            comment_id = await self._commenter.upsert_comment(
                notice.quarantined.repository,
                pull_request,
                marker=notice.marker,
                body=notice.body(),
                comment_id=notice.comment_id,
            )
        except Exception:
            # Left owed: the next live pass offers it again. The marker is what
            # keeps a post that landed before this raised from being doubled.
            logger.exception("Could not post the quarantine notice for %s", notice.key)
            return False
        await self._save(
            notice.model_copy(
                update={"status": "posted", "pull_request": pull_request, "comment_id": comment_id}
            )
        )
        return True

    async def _save(self, notice: QuarantineNotice) -> None:
        assert self._store is not None
        await self._store.save(self.PROJECTION_NAME, notice.key, notice.model_dump(mode="json"))

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """One notice per (execution, phase, repository)."""
        return str(todo_item.get("key", ""))

    async def clear_all_data(self) -> None:
        if self._store is not None:
            await self._store.delete_all(self.PROJECTION_NAME)
