"""#1547: a quarantine reaches the PR exactly once, from the live side only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from event_sourcing import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    RemoteBranchReading,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    FailExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.lifecycle_events import (
    failed_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    QuarantinedRef,
)
from syn_domain.contexts.orchestration.slices.notify_quarantine import (
    QuarantineNoticeProcessManager,
)

REF = "refs/syn/lost/exec-q1/implement"
SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


@dataclass
class _Commenter:
    """A forge that remembers comments by id, as GitHub does."""

    comments: dict[int, str] = field(default_factory=dict)
    posts: int = 0
    edits: int = 0

    async def upsert_comment(
        self, repository: str, pull_request: int, *, marker: str, body: str, comment_id: int | None
    ) -> int:
        assert repository == "acme/widget"
        assert pull_request == 42
        assert body.startswith(marker)
        if comment_id is not None:
            self.edits += 1
            self.comments[comment_id] = body
            return comment_id
        self.posts += 1
        new_id = 9000 + self.posts
        self.comments[new_id] = body
        return new_id


@dataclass
class _Forge:
    open_pr: int | None = None

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        return RemoteBranchReading(
            repository=repository, branch=branch, readable=True, open_pull_request=self.open_pr
        )


def _failed(*, commit: str = SHA, pull_request: int | None = 42, nonce: int = 1) -> EventEnvelope:
    """The event as the aggregate builds it, so a hop that drops the refs fails here."""
    command = FailExecutionCommand(
        execution_id="exec-q1",
        error="phase timed out",
        error_type="TimeoutError",
        failed_phase_id="implement",
        completed_phases=0,
        total_phases=1,
        classification=FailureClassification.UNCLASSIFIED,
        quarantined=(
            QuarantinedRef(
                repository="acme/widget",
                branch="feat/thing",
                ref=REF,
                commit=commit,
                commit_count=2,
                pull_request=pull_request,
            ),
        ),
    )
    event = failed_event(command, "wf-1")
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            aggregate_id="exec-q1",
            aggregate_type="WorkflowExecution",
            aggregate_nonce=nonce,
            event_type="WorkflowFailed",
            global_nonce=nonce,
        ),
    )


def _manager(forge: _Forge | None = None) -> tuple[QuarantineNoticeProcessManager, _Commenter]:
    commenter = _Commenter()
    return (
        QuarantineNoticeProcessManager(
            commenter=commenter, store=InMemoryProjectionStore(), branches=forge
        ),
        commenter,
    )


@pytest.mark.asyncio
async def test_replaying_the_quarantine_posts_nothing() -> None:
    manager, commenter = _manager()
    for _ in range(3):
        await manager.handle_event(_failed(), MemoryCheckpointStore())
    # handle_event is all a catch-up replay ever calls.
    assert commenter.posts == 0 and commenter.edits == 0


@pytest.mark.asyncio
async def test_live_posts_exactly_once_naming_ref_sha_phase_and_fetch() -> None:
    manager, commenter = _manager()
    await manager.handle_event(_failed(), MemoryCheckpointStore())
    assert await manager.process_pending() == 1
    # A second pass, and the same event replayed after it, owe nothing more.
    assert await manager.process_pending() == 0
    await manager.handle_event(_failed(), MemoryCheckpointStore())
    assert await manager.process_pending() == 0
    assert commenter.posts == 1 and commenter.edits == 0
    (body,) = commenter.comments.values()
    assert REF in body and SHA in body and "`implement`" in body
    assert f"git fetch origin {REF}:refs/heads/recovered/exec-q1/implement" in body
    assert "/workspace" not in body and "token" not in body.lower()


@pytest.mark.asyncio
async def test_a_retry_updates_the_same_comment() -> None:
    manager, commenter = _manager()
    await manager.handle_event(_failed(), MemoryCheckpointStore())
    await manager.process_pending()
    retried = "f" * 40
    await manager.handle_event(_failed(commit=retried, nonce=2), MemoryCheckpointStore())
    assert await manager.process_pending() == 1
    assert commenter.posts == 1 and commenter.edits == 1
    assert list(commenter.comments) == [9001]
    assert retried in commenter.comments[9001]


@pytest.mark.asyncio
async def test_with_no_pr_yet_it_posts_once_one_opens() -> None:
    forge = _Forge()
    manager, commenter = _manager(forge)
    await manager.handle_event(_failed(pull_request=None), MemoryCheckpointStore())
    assert await manager.process_pending() == 0
    assert commenter.posts == 0
    forge.open_pr = 42
    assert await manager.process_pending() == 1
    assert commenter.posts == 1


@pytest.mark.asyncio
async def test_a_pr_opening_long_after_the_failure_still_gets_the_notice() -> None:
    forge = _Forge()
    manager, commenter = _manager(forge)
    envelope = _failed(pull_request=None)
    old = envelope.event.model_copy(update={"failed_at": datetime.now(UTC) - timedelta(days=30)})
    await manager.handle_event(
        EventEnvelope(event=old, metadata=envelope.metadata), MemoryCheckpointStore()
    )
    assert await manager.process_pending() == 0
    forge.open_pr = 42
    assert await manager.process_pending() == 1
    assert commenter.posts == 1
