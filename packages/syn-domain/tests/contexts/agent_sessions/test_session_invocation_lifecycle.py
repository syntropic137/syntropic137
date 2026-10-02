"""Controlled invocations retain identity and outcome across aggregate replay."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.agent_sessions import (
    AgentSessionAggregate,
    InvocationStatus,
    RecordSessionInvocationCommand,
    SessionInvocationState,
    StartSessionCommand,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationBindingConflictedEvent import (
    SessionInvocationBindingConflictedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)

pytestmark = pytest.mark.unit


def _aggregate() -> AgentSessionAggregate:
    aggregate = AgentSessionAggregate()
    aggregate.start_session(
        StartSessionCommand(
            aggregate_id="session",
            workflow_id="definition",
            execution_id="run",
            phase_id="phase",
            agent_provider="claude",
        )
    )
    return aggregate


def _record(aggregate: AgentSessionAggregate, state: SessionInvocationState) -> None:
    aggregate.record_invocation(
        RecordSessionInvocationCommand(aggregate_id="session", invocation=state)
    )


def test_replayed_invocation_records_conflicting_binding_and_preserves_billing_identity() -> None:
    aggregate = _aggregate()
    intent = SessionInvocationState(
        invocation_id="invocation", attempt_id="attempt", harness="claude"
    )
    _record(aggregate, intent)
    bound = intent.model_copy(
        update={"native_session_id": "opaque/native", "status": InvocationStatus.LAUNCHED}
    )
    _record(aggregate, bound)
    restored = AgentSessionAggregate()
    restored.rehydrate(aggregate.get_uncommitted_events())
    assert str(restored.id) == "session"
    assert restored.invocations == (bound,)
    _record(restored, bound)
    assert restored.get_uncommitted_events() == []
    # A contradicting bind is recorded as evidence; the first binding stands.
    _record(restored, bound.model_copy(update={"native_session_id": "another"}))
    (conflict,) = restored.get_uncommitted_events()
    assert isinstance(conflict.event, SessionInvocationBindingConflictedEvent)
    assert (
        conflict.event.bound_native_session_id,
        conflict.event.conflicting_native_session_id,
    ) == ("opaque/native", "another")
    assert restored.invocations == (bound,)
    # The same contradiction again, even after replay, adds nothing.
    _record(restored, bound.model_copy(update={"native_session_id": "another"}))
    assert len(restored.get_uncommitted_events()) == 1
    replayed = AgentSessionAggregate()
    replayed.rehydrate([*aggregate.get_uncommitted_events(), conflict])
    _record(replayed, bound.model_copy(update={"native_session_id": "another"}))
    assert replayed.get_uncommitted_events() == []
    assert replayed.invocations == (bound,)
    with pytest.raises(ValueError, match="attempt or harness"):
        _record(restored, bound.model_copy(update={"harness": "codex"}))
    assert restored.tokens.total_tokens == 0


def test_unregistered_and_terminal_transitions_are_rejected_but_late_binding_is_valid() -> None:
    aggregate = _aggregate()
    intent = SessionInvocationState(
        invocation_id="invocation", attempt_id="attempt", harness="claude"
    )
    with pytest.raises(ValueError, match="registered before"):
        _record(aggregate, intent.model_copy(update={"status": InvocationStatus.LAUNCHED}))
    _record(aggregate, intent)
    failed = intent.model_copy(update={"status": InvocationStatus.FAILED})
    _record(aggregate, failed)
    with pytest.raises(ValueError, match="terminal"):
        _record(aggregate, intent)
    _record(aggregate, failed.model_copy(update={"native_session_id": "late"}))
    assert aggregate.invocations[0].status == InvocationStatus.FAILED


def _manager(repo: AsyncMock) -> SessionLifecycleManager:
    return SessionLifecycleManager(
        repository=repo,
        session_id="session",
        workflow_id="definition",
        execution_id="run",
        phase_id="phase",
        agent_provider="claude",
        agent_model=None,
    )


async def test_registration_failure_propagates_before_controlled_launch() -> None:
    repo = AsyncMock()
    manager = _manager(repo)
    await manager.start()
    repo.save.side_effect = ConnectionError("event store unavailable")
    with pytest.raises(ConnectionError):
        await manager.prepare_invocation("claude")


async def test_capacity_retry_keeps_both_attempts_and_their_native_bindings() -> None:
    manager = _manager(AsyncMock())
    await manager.start()
    await manager.prepare_invocation("claude")
    await manager.mark_launched()
    await manager.finish_invocation(native_session_id="first", status=InvocationStatus.FAILED)
    await manager.prepare_invocation("claude")
    await manager.mark_launched()
    await manager.finish_invocation(native_session_id="second", status=InvocationStatus.COMPLETED)
    assert manager.session is not None
    first, second = manager.session.invocations
    assert first.invocation_id != second.invocation_id
    assert first.attempt_id != second.attempt_id
    assert first.native_session_id == "first"
    assert second.native_session_id == "second"
    assert first.status == InvocationStatus.FAILED
    assert second.status == InvocationStatus.COMPLETED
    assert manager.session.tokens.total_tokens == 0


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (RuntimeError("process failed"), InvocationStatus.FAILED),
        (asyncio.CancelledError(), InvocationStatus.CANCELLED),
    ],
)
async def test_dispatch_exception_leaves_terminal_invocation(
    failure: BaseException,
    expected: InvocationStatus,
) -> None:
    from syn_domain.contexts.orchestration.slices.execute_workflow.invocation_attempt import (
        registered_attempt,
    )

    manager = _manager(AsyncMock())
    await manager.start()
    with pytest.raises(type(failure)):
        async with registered_attempt(manager, "claude"):
            await manager.mark_launched()
            raise failure
    assert manager.session is not None
    assert manager.session.invocations[0].status == expected


async def test_registration_failure_never_enters_dispatch_body() -> None:
    from syn_domain.contexts.orchestration.slices.execute_workflow.invocation_attempt import (
        registered_attempt,
    )

    repository = AsyncMock()
    manager = _manager(repository)
    await manager.start()
    repository.save.side_effect = ConnectionError("durability unavailable")
    entered = False
    with pytest.raises(ConnectionError):
        async with registered_attempt(manager, "claude"):
            entered = True
    assert not entered


def test_failed_launch_is_terminal_and_cannot_acquire_native_identity() -> None:
    aggregate = _aggregate()
    intent = SessionInvocationState(
        invocation_id="invocation", attempt_id="attempt", harness="codex"
    )
    _record(aggregate, intent)
    failed = intent.model_copy(update={"status": InvocationStatus.LAUNCH_FAILED})
    _record(aggregate, failed)
    restored = AgentSessionAggregate()
    restored.rehydrate(aggregate.get_uncommitted_events())
    assert restored.invocations == (failed,)
    with pytest.raises(ValueError, match="native identity"):
        _record(restored, failed.model_copy(update={"native_session_id": "impossible"}))
    with pytest.raises(ValueError, match="terminal"):
        _record(restored, intent.model_copy(update={"status": InvocationStatus.LAUNCHED}))


def test_observed_launch_cannot_be_reclassified_as_launch_failure() -> None:
    aggregate = _aggregate()
    intent = SessionInvocationState(
        invocation_id="invocation", attempt_id="attempt", harness="codex"
    )
    _record(aggregate, intent)
    _record(aggregate, intent.model_copy(update={"status": InvocationStatus.LAUNCHED}))
    with pytest.raises(ValueError, match="observed launch"):
        _record(aggregate, intent.model_copy(update={"status": InvocationStatus.LAUNCH_FAILED}))


def test_conflicting_bind_with_a_terminal_outcome_keeps_first_binding_and_advances() -> None:
    aggregate = _aggregate()
    intent = SessionInvocationState(
        invocation_id="invocation", attempt_id="attempt", harness="codex"
    )
    _record(aggregate, intent)
    launched = intent.model_copy(
        update={"status": InvocationStatus.LAUNCHED, "native_session_id": "first"}
    )
    _record(aggregate, launched)
    _record(
        aggregate,
        launched.model_copy(
            update={"status": InvocationStatus.COMPLETED, "native_session_id": "second"}
        ),
    )
    (state,) = aggregate.invocations
    assert (state.status, state.native_session_id) == (InvocationStatus.COMPLETED, "first")
    names = [type(item.event).__name__ for item in aggregate.get_uncommitted_events()]
    assert names[-2:] == [
        "SessionInvocationBindingConflictedEvent",
        "SessionInvocationRecordedEvent",
    ]
    # A status update that carries no identity never unbinds.
    _record(aggregate, state.model_copy(update={"native_session_id": None}))
    assert aggregate.invocations == (state,)


def test_duplicate_register_bind_and_finish_are_idempotent() -> None:
    aggregate = _aggregate()
    intent = SessionInvocationState(
        invocation_id="invocation", attempt_id="attempt", harness="claude"
    )
    launched = intent.model_copy(update={"status": InvocationStatus.LAUNCHED})
    bound = launched.model_copy(update={"native_session_id": "native"})
    finished = bound.model_copy(update={"status": InvocationStatus.COMPLETED})
    counts = []
    for state in (intent, intent, launched, launched, bound, bound, finished, finished):
        _record(aggregate, state)
        counts.append(len(aggregate.get_uncommitted_events()))
    # Session start + one event per distinct transition; every repeat adds nothing.
    assert counts == [2, 2, 3, 3, 4, 4, 5, 5]
