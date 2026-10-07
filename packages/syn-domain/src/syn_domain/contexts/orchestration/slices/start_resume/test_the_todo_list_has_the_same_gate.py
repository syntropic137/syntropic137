"""The to-do list is the SECOND reader of a renamed event (#1471 review).

The aggregate spends the parent's one resume; this process manager decides
whether a start is OWED. Both read the same event, so a guard on one of them
is not a guard.

It dispatched on `envelope.metadata.event_type` alone and never looked at the
payload. Under ADR-023 a payload the typed validator refused replays as a
`GenericDomainEvent` with its type intact, so a pre-rename un-pause would put a
start on this list for a child nobody admitted - and `process_pending` would
then try to start it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata, GenericDomainEvent

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.start_resume.ResumeStartProcessManager import (
    ResumeStartProcessManager,
)

pytestmark = pytest.mark.unit

PARENT = "exec-parent-1"


class _Checkpoints:
    """Accepts a checkpoint and remembers nothing; the record is the assertion."""

    async def save_checkpoint(self, checkpoint: object) -> None:
        del checkpoint

    async def get_checkpoint(self, projection_name: str) -> None:
        del projection_name

    async def delete_checkpoint(self, projection_name: str) -> None:
        del projection_name


def _generic(event_type: str, **payload: object) -> EventEnvelope[DomainEvent]:
    """An envelope exactly as `grpc_client` builds one when typed validation fails."""
    return EventEnvelope(
        event=GenericDomainEvent(**payload, event_type=event_type),
        metadata=EventMetadata(
            aggregate_id=PARENT,
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            event_type=event_type,
            global_nonce=1,
        ),
    )


def _unpause_payload():
    return {
        "workflow_id": "wf-1",
        "execution_id": PARENT,
        "phase_id": "plan",
        "resumed_at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
    }


def _resume_payload(**overrides: object):
    return {
        "workflow_id": "wf-1",
        "execution_id": PARENT,
        "resume_execution_id": "exec-child-1",
        "inherited_phases": [],
        "resume_phase_id": "implement",
        "resumed_at": datetime(2026, 9, 29, tzinfo=UTC).isoformat(),
        **overrides,
    }


def _forked_payload():
    return {
        "workflow_id": "wf-1",
        "execution_id": PARENT,
        "fork_execution_id": "exec-child-1",
        "inherited_phases": [],
        "resume_phase_id": "implement",
        "forked_at": datetime(2026, 9, 26, tzinfo=UTC).isoformat(),
    }


async def _owed(store: InMemoryProjectionStore) -> bool:
    return await store.get(ResumeStartProcessManager.PROJECTION_NAME, PARENT) is not None


def _manager(store: InMemoryProjectionStore) -> ResumeStartProcessManager:
    return ResumeStartProcessManager(resume_starter=None, store=store)


class TestWhatOwesAStart:
    async def test_a_legacy_unpause_owes_nothing(self) -> None:
        store = InMemoryProjectionStore()

        await _manager(store).handle_event(
            _generic("ExecutionResumed", **_unpause_payload()), _Checkpoints()
        )

        assert not await _owed(store)

    async def test_a_real_resume_owes_one(self) -> None:
        """The control: the gate must not refuse everything.

        Without this, a manager that recorded nothing at all would make the
        test above pass while breaking every resume.
        """
        store = InMemoryProjectionStore()

        await _manager(store).handle_event(
            _generic("ExecutionResumed", **_resume_payload()), _Checkpoints()
        )

        assert await _owed(store)

    async def test_a_pre_rename_forked_event_owes_one(self) -> None:
        """The other half: dropping it leaves a child that never starts."""
        store = InMemoryProjectionStore()

        await _manager(store).handle_event(
            _generic("ExecutionForked", **_forked_payload()), _Checkpoints()
        )

        assert await _owed(store)

    async def test_an_ambiguous_payload_owes_nothing_and_is_not_swallowed(self) -> None:
        """Both markers cannot be resolved by guesswork.

        The manager reports the failure rather than recording a start it
        cannot justify, so the result is not SUCCESS and nothing is owed.
        """
        from event_sourcing import ProjectionResult

        store = InMemoryProjectionStore()
        both = {**_unpause_payload(), "resume_execution_id": "exec-child-1"}

        result = await _manager(store).handle_event(
            _generic("ExecutionResumed", **both), _Checkpoints()
        )

        assert result is not ProjectionResult.SUCCESS
        assert not await _owed(store)


class TestBothReadersAgree:
    async def test_the_forked_event_is_subscribed_at_all(self) -> None:
        """A payload gate is unreachable if the event never arrives.

        The coordinator filters by `get_subscribed_event_types`, so omitting
        the pre-rename name here would drop the event before any branch ran -
        and every test above would still pass, because they call
        `handle_event` directly.
        """
        subscribed = _manager(InMemoryProjectionStore()).get_subscribed_event_types()

        assert subscribed is not None
        assert "ExecutionForked" in subscribed
        assert "ExecutionResumed" in subscribed


class TestAnUnstartableResumeSettlesRatherThanStranding:
    """Round 2 of the #1471 review called a recorded-but-unstartable resume a
    defect. It is the designed path, and this pins that rather than arguing it.

    A stored resume whose child id did not survive replay (ADR-023 can drop a
    field) DOES get a to-do record. The alternative - recording nothing - would
    silently lose the fact that a resume was admitted and cannot be started,
    leaving an operator with a parent that refuses a second resume and no
    reason anywhere.

    Instead `StartResumeHandler.validate` refuses it BEFORE dispatch with
    "cannot be named", the refusal is recorded against the record, and the
    attempt ceiling settles it as `failed` with that reason. Bounded, visible,
    and identical for a pre-rename `ExecutionForked` and a post-rename
    `ExecutionResumed`, which is the symmetry the review asked for.
    """

    @staticmethod
    async def _settled(event_type: str, **payload: object) -> str:
        from datetime import datetime as _dt

        from syn_domain.contexts.orchestration.slices.start_resume.value_objects import (
            MAX_START_ATTEMPTS,
            ResumeStartRecord,
        )

        store = InMemoryProjectionStore()

        class _CannotName:
            def holds_start(self, parent_execution_id: str) -> bool:
                del parent_execution_id
                return False

            async def start_resume(self, parent_execution_id: str, *, on_failure: object) -> None:
                del parent_execution_id, on_failure
                msg = "Execution exec-parent-1 admitted a resume its stream cannot name"
                raise ValueError(msg)

        manager = ResumeStartProcessManager(resume_starter=_CannotName(), store=store)
        await manager.handle_event(_generic(event_type, **payload), _Checkpoints())

        record = ResumeStartRecord(
            parent_execution_id=PARENT,
            recorded_at=_dt.now(UTC),
            attempts=MAX_START_ATTEMPTS - 1,
        )
        await manager._save(record)
        await manager._start(record)

        row = await store.get(ResumeStartProcessManager.PROJECTION_NAME, PARENT)
        assert row is not None, "the attempt recorded nothing"
        return ResumeStartRecord.model_validate(row).status

    async def test_a_nameless_pre_rename_resume_settles_failed(self) -> None:
        nameless = {
            "workflow_id": "wf-1",
            "execution_id": PARENT,
            "inherited_phases": [],
            "resume_phase_id": "implement",
            "forked_at": datetime(2026, 9, 26, tzinfo=UTC).isoformat(),
        }

        assert await self._settled("ExecutionForked", **nameless) == "failed"

    async def test_a_nameless_post_rename_resume_settles_the_same_way(self) -> None:
        """The symmetry: the two names must not behave differently."""
        nameless = {
            "workflow_id": "wf-1",
            "execution_id": PARENT,
            "inherited_phases": [],
            "resume_phase_id": "implement",
            "resumed_at": datetime(2026, 9, 29, tzinfo=UTC).isoformat(),
        }

        assert await self._settled("ExecutionResumed", **nameless) == "failed"
