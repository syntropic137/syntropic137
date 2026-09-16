"""Tests for SessionLifecycleManager."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from event_sourcing import DomainEvent, EventEnvelope  # noqa: TC002

from syn_domain.contexts.agent_sessions import AgentLaunch, SessionStatus
from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.events.OperationRecordedEvent import (
    OperationRecordedEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionCompletedEvent import (
    SessionCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)


class FakeSessionRepository:
    """An event-sourced repository double: a stream per aggregate.

    ``get_by_id`` rehydrates a FRESH aggregate from the saved stream rather
    than returning the object it was handed. ``complete_success`` now writes
    through the agent_sessions slice handlers, which load by id (#1034), so
    an AsyncMock cannot show whether anything was actually persisted - it
    hands the handler a mock session that accepts every call and records
    nothing.
    """

    def __init__(self) -> None:
        self.streams: dict[str, list[EventEnvelope[DomainEvent]]] = {}

    async def get_by_id(self, aggregate_id: str) -> AgentSessionAggregate | None:
        stream = self.streams.get(aggregate_id)
        if not stream:
            return None
        session = AgentSessionAggregate()
        session.rehydrate(stream)
        return session

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        self.streams.setdefault(str(aggregate.id), []).extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: AgentSessionAggregate) -> None:
        await self.save(aggregate)

    async def exists(self, aggregate_id: str) -> bool:
        return aggregate_id in self.streams

    def recorded_events(self, aggregate_id: str) -> list[DomainEvent]:
        """The domain events on the stream, as downstream readers see them."""
        return [envelope.event for envelope in self.streams.get(aggregate_id, [])]


def _make_manager(
    repo: AsyncMock | None = None,
) -> SessionLifecycleManager:
    if repo is None:
        repo = AsyncMock()
    return SessionLifecycleManager(
        repository=repo,
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="phase-1",
        agent_provider="claude",
        agent_model="claude-sonnet-4-20250514",
    )


class TestStart:
    @pytest.mark.asyncio
    async def test_creates_and_saves_session(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)

        await mgr.start()

        assert mgr.session is not None
        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_when_repo_is_none(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )

        await mgr.start()

        assert mgr.session is None


class TestMarkLaunched:
    """Tests for mark_launched - the discriminator fact for #1047/#1065."""

    @pytest.mark.asyncio
    async def test_records_agent_launched_on_session(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.reset_mock()

        await mgr.mark_launched()

        session = mgr.session
        assert session is not None
        assert session.agent_launch is AgentLaunch.LAUNCHED
        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )

        # Should not raise
        await mgr.mark_launched()

    @pytest.mark.asyncio
    async def test_a_failed_launch_write_still_reaches_the_completion_event(self) -> None:
        """Swallowing the save must cost promptness, never the answer.

        The store is down for exactly the launch write and healthy again by
        completion - the shape that used to lose the fact outright, because
        it was only ever recorded by that one write. Asserting "no exception
        escaped" would have passed then too, so this asserts the consumer:
        the SessionCompleted event that outlives the aggregate and feeds every
        rebuilt projection still says LAUNCHED (#1065).
        """
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.side_effect = RuntimeError("db down")

        await mgr.mark_launched()

        repo.save.side_effect = None
        await mgr.complete_failure(error_message="agent crashed mid-run")

        session = mgr.session
        assert session is not None
        completed = [
            e.event
            for e in session.get_uncommitted_events()
            if isinstance(e.event, SessionCompletedEvent)
        ]
        assert len(completed) == 1
        assert completed[0].agent_launch is AgentLaunch.LAUNCHED

    @pytest.mark.asyncio
    async def test_agent_launched_survives_subsequent_complete_failure(self) -> None:
        """An agent that launched and then failed must still read as LAUNCHED
        after complete_failure runs - complete_failure only sets terminal
        status, it must never clear the launch fact (#1047, #1065).
        """
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()

        await mgr.mark_launched()
        await mgr.complete_failure(error_message="agent crashed mid-run")

        session = mgr.session
        assert session is not None
        assert session.agent_launch is AgentLaunch.LAUNCHED


class TestCompleteSuccess:
    @pytest.mark.asyncio
    async def test_records_tokens_and_completes(self) -> None:
        """Both writes must land on the stream every projection replays."""
        repo = FakeSessionRepository()
        mgr = _make_manager(repo)
        await mgr.start()

        await mgr.complete_success(
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=150,
            duration_seconds=1.5,
            source="test",
        )

        assert [type(e).__name__ for e in repo.recorded_events("sess-1")] == [
            "SessionStartedEvent",
            "OperationRecordedEvent",
            "SessionCompletedEvent",
        ]

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_session_aggregate_receives_authoritative_tokens(self) -> None:
        """Regression: session must reflect authoritative CLI result tokens.

        Per-turn assistant events may report input_tokens=0 (cache hits),
        but the CLI result event has the true totals. The processor must
        pass those authoritative values through to session completion.
        See: ISS-405 / hotfix-403.
        """
        repo = FakeSessionRepository()
        mgr = _make_manager(repo)
        await mgr.start()

        # Authoritative values from CLI result event (includes cache tokens)
        await mgr.complete_success(
            input_tokens=6939,
            output_tokens=517,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=7456,
            duration_seconds=303.0,
            source="processor",
        )

        # Read back from the store, not off the manager: the manager's own
        # copy proves nothing about what a later reader will see.
        persisted = await repo.get_by_id("sess-1")
        assert persisted is not None
        assert persisted.tokens.input_tokens == 6939
        assert persisted.tokens.output_tokens == 517
        assert persisted.tokens.total_tokens == 7456

    @pytest.mark.asyncio
    async def test_skips_token_recording_when_zero(self) -> None:
        repo = FakeSessionRepository()
        mgr = _make_manager(repo)
        await mgr.start()

        await mgr.complete_success(
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=0.0,
            source="test",
        )

        events = repo.recorded_events("sess-1")
        assert not any(isinstance(e, OperationRecordedEvent) for e in events)
        assert any(isinstance(e, SessionCompletedEvent) for e in events)

    @pytest.mark.asyncio
    async def test_a_failed_launch_write_still_reaches_a_successful_completion(self) -> None:
        """The launch fact must survive the handover to the slice handlers.

        ``mark_launched`` swallows its save failure and relies on the event
        riding this manager's next save (#1047, #1065). ``complete_success``
        no longer writes through that aggregate - the handlers load their own
        copy - so without the flush that opens ``complete_success`` the fact
        is dropped between the two. The consumer asserted here is the
        SessionCompleted event on the stream, which is what every rebuilt
        projection reads long after the aggregate is gone.
        """
        repo = FakeSessionRepository()
        mgr = _make_manager(repo)
        await mgr.start()

        failing = AsyncMock(side_effect=RuntimeError("db down"))
        original_save = repo.save
        repo.save = failing  # type: ignore[method-assign]
        await mgr.mark_launched()
        repo.save = original_save  # type: ignore[method-assign]

        await mgr.complete_success(
            input_tokens=10,
            output_tokens=5,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=15,
            duration_seconds=1.0,
            source="test",
        )

        completed = [
            e for e in repo.recorded_events("sess-1") if isinstance(e, SessionCompletedEvent)
        ]
        assert len(completed) == 1
        assert completed[0].agent_launch is AgentLaunch.LAUNCHED

    @pytest.mark.asyncio
    async def test_the_session_this_manager_exposes_is_not_left_behind_the_stream(self) -> None:
        """``session`` must not hand back a copy the store has moved past.

        The handlers advance the stream without touching this manager's
        aggregate, so the one it was holding is two events stale the moment
        ``complete_success`` returns. Anything that then read ``session``
        would be told the run is still RUNNING (#1034).
        """
        repo = FakeSessionRepository()
        mgr = _make_manager(repo)
        await mgr.start()

        await mgr.complete_success(
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=150,
            duration_seconds=1.5,
            source="test",
        )

        session = mgr.session
        assert session is not None
        assert session.status is SessionStatus.COMPLETED
        assert session.tokens.total_tokens == 150

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )

        # Should not raise
        await mgr.complete_success(
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=150,
            duration_seconds=1.0,
            source="test",
        )


class TestCompleteFailure:
    @pytest.mark.asyncio
    async def test_completes_with_error(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.reset_mock()

        await mgr.complete_failure(error_message="something broke")

        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_secondary_errors(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.side_effect = RuntimeError("db down")

        # Should not raise
        await mgr.complete_failure(error_message="original error")

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )
        await mgr.complete_failure(error_message="err")


class TestCompleteCancelled:
    @pytest.mark.asyncio
    async def test_completes_as_cancelled(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.reset_mock()

        await mgr.complete_cancelled(reason="user interrupt")

        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_secondary_errors(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.side_effect = RuntimeError("db down")

        # Should not raise
        await mgr.complete_cancelled(reason="interrupted")

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )
        await mgr.complete_cancelled(reason="cancelled")
