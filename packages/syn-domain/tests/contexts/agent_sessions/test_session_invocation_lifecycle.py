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


def test_replayed_invocation_rejects_conflicting_binding_and_preserves_billing_identity() -> None:
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
    with pytest.raises(ValueError, match="native identity"):
        _record(restored, bound.model_copy(update={"native_session_id": "another"}))
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
