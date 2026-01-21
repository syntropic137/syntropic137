"""Level 4 Verification: Agent Session Tracking Roundtrip Tests.

These tests verify that agent session aggregates:
1. Persist correctly to the real event store
2. Can be reloaded with full state restored
3. Accumulate token/cost metrics correctly across operations

Level 4 = Outcome Verification: Real database, real persistence, real reads.

Run with:
    # Start infrastructure
    docker compose -f docker/docker-compose.dev.yaml up -d

    # Run integration tests
    uv run pytest -m integration packages/aef-domain/tests/integration/test_session_tracking_roundtrip.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository

    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
        AgentSessionAggregate,
    )


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.integration
class TestAgentSessionRoundtrip:
    """Level 4 tests: Verify agent session persists to real event store."""

    async def test_start_session_persists_to_event_store(
        self,
        agent_session_repository: EventStoreRepository[AgentSessionAggregate],
        unique_session_id: str,
    ) -> None:
        """Level 4: Start command persists SessionStartedEvent."""
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.slices.start_session.StartSessionCommand import (
            StartSessionCommand,
        )

        # Arrange: Create aggregate and execute command
        aggregate = AgentSessionAggregate()
        command = StartSessionCommand(
            aggregate_id=unique_session_id,
            workflow_id="workflow-session-test",
            execution_id="exec-123",
            phase_id="phase-research",
            milestone_id=None,
            agent_provider="anthropic",
            agent_model="claude-sonnet-4-20250514",
            metadata={"test": True},
        )
        aggregate._handle_command(command)

        # Act: Save to REAL event store
        await agent_session_repository.save(aggregate)

        # Assert: Load back and verify state
        loaded = await agent_session_repository.load(unique_session_id)

        assert loaded is not None, "Session should be loadable from event store"
        assert loaded.id == unique_session_id
        assert loaded.workflow_id == "workflow-session-test"
        assert loaded._phase_id == "phase-research"
        assert loaded._agent_provider == "anthropic"
        assert loaded._agent_model == "claude-sonnet-4-20250514"
        assert loaded.version == 1

    async def test_record_operation_persists_to_event_store(
        self,
        agent_session_repository: EventStoreRepository[AgentSessionAggregate],
        unique_session_id: str,
    ) -> None:
        """Level 4: Operation recording persists OperationRecordedEvent."""
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.slices.record_operation.RecordOperationCommand import (
            RecordOperationCommand,
        )
        from aef_domain.contexts.sessions.slices.start_session.StartSessionCommand import (
            StartSessionCommand,
        )

        # Arrange: Create and start session
        aggregate = AgentSessionAggregate()
        aggregate._handle_command(
            StartSessionCommand(
                aggregate_id=unique_session_id,
                workflow_id="workflow-ops",
                execution_id="exec-ops",
                phase_id="phase-1",
                agent_provider="anthropic",
                agent_model="claude-sonnet-4-20250514",
            )
        )
        await agent_session_repository.save(aggregate)

        # Act: Load, record operation, save
        loaded = await agent_session_repository.load(unique_session_id)
        assert loaded is not None

        loaded._handle_command(
            RecordOperationCommand(
                aggregate_id=unique_session_id,
                operation_type="message_request",
                input_tokens=1500,
                output_tokens=800,
                total_tokens=2300,
                duration_seconds=2.5,
            )
        )
        await agent_session_repository.save(loaded)

        # Assert: Reload and verify token accumulation
        reloaded = await agent_session_repository.load(unique_session_id)
        assert reloaded is not None
        assert reloaded.version == 2
        assert reloaded.tokens.input_tokens == 1500
        assert reloaded.tokens.output_tokens == 800
        assert reloaded.tokens.total_tokens == 2300
        # Cost is calculated from tokens, not explicitly set
        assert reloaded.cost.total_cost_usd >= 0

    async def test_complete_session_persists_to_event_store(
        self,
        agent_session_repository: EventStoreRepository[AgentSessionAggregate],
        unique_session_id: str,
    ) -> None:
        """Level 4: Session completion persists SessionCompletedEvent."""
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions._shared.value_objects import (
            SessionStatus,
        )
        from aef_domain.contexts.sessions.slices.complete_session.CompleteSessionCommand import (
            CompleteSessionCommand,
        )
        from aef_domain.contexts.sessions.slices.start_session.StartSessionCommand import (
            StartSessionCommand,
        )

        # Arrange: Create and start session
        aggregate = AgentSessionAggregate()
        aggregate._handle_command(
            StartSessionCommand(
                aggregate_id=unique_session_id,
                workflow_id="workflow-complete",
                execution_id="exec-complete",
                phase_id="phase-1",
                agent_provider="anthropic",
                agent_model="claude-sonnet-4-20250514",
            )
        )
        await agent_session_repository.save(aggregate)

        # Act: Load, complete session, save
        loaded = await agent_session_repository.load(unique_session_id)
        assert loaded is not None

        loaded._handle_command(
            CompleteSessionCommand(
                aggregate_id=unique_session_id,
                success=True,
                error_message=None,
                final_artifact_id="artifact-final",
            )
        )
        await agent_session_repository.save(loaded)

        # Assert: Reload and verify completed state
        reloaded = await agent_session_repository.load(unique_session_id)
        assert reloaded is not None
        assert reloaded.status == SessionStatus.COMPLETED
        assert reloaded._completed_at is not None


class TestAgentSessionTokenAccumulation:
    """Level 4 tests: Verify token/cost accumulation across operations."""

    async def test_multiple_operations_accumulate_correctly(
        self,
        agent_session_repository: EventStoreRepository[AgentSessionAggregate],
        unique_session_id: str,
    ) -> None:
        """Level 4: Multiple operations accumulate tokens and costs correctly."""
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.slices.record_operation.RecordOperationCommand import (
            RecordOperationCommand,
        )
        from aef_domain.contexts.sessions.slices.start_session.StartSessionCommand import (
            StartSessionCommand,
        )

        # Arrange: Start session
        aggregate = AgentSessionAggregate()
        aggregate._handle_command(
            StartSessionCommand(
                aggregate_id=unique_session_id,
                workflow_id="workflow-accumulate",
                execution_id="exec-accumulate",
                phase_id="phase-1",
                agent_provider="anthropic",
                agent_model="claude-sonnet-4-20250514",
            )
        )
        await agent_session_repository.save(aggregate)

        # Record 5 operations
        operations = [
            {"input": 1000, "output": 500, "type": "message_request"},
            {"input": 800, "output": 200, "type": "tool_execution"},
            {"input": 1200, "output": 600, "type": "message_response"},
            {"input": 500, "output": 100, "type": "tool_completed"},
            {"input": 1500, "output": 800, "type": "agent_request"},
        ]

        for op in operations:
            loaded = await agent_session_repository.load(unique_session_id)
            assert loaded is not None
            total = op["input"] + op["output"]
            loaded._handle_command(
                RecordOperationCommand(
                    aggregate_id=unique_session_id,
                    operation_type=op["type"],
                    input_tokens=op["input"],
                    output_tokens=op["output"],
                    total_tokens=total,
                    duration_seconds=1.0,
                )
            )
            await agent_session_repository.save(loaded)

        # Assert: Verify accumulated totals
        final = await agent_session_repository.load(unique_session_id)
        assert final is not None

        # Expected: 1000+800+1200+500+1500 = 5000 input
        # Expected: 500+200+600+100+800 = 2200 output
        # Expected: 5000+2200 = 7200 total
        assert final.tokens.input_tokens == 5000
        assert final.tokens.output_tokens == 2200
        assert final.tokens.total_tokens == 7200
        assert final.cost.total_cost_usd >= 0  # Cost calculated from tokens
        assert final.operation_count == 5
        assert final.version == 6  # 1 start + 5 operations


class TestAgentSessionLifecycle:
    """Level 4 tests: Full session lifecycle with real persistence."""

    async def test_full_session_lifecycle(
        self,
        agent_session_repository: EventStoreRepository[AgentSessionAggregate],
        unique_session_id: str,
    ) -> None:
        """Level 4: Complete session lifecycle persists and replays correctly."""
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions._shared.value_objects import (
            SessionStatus,
        )
        from aef_domain.contexts.sessions.slices.complete_session.CompleteSessionCommand import (
            CompleteSessionCommand,
        )
        from aef_domain.contexts.sessions.slices.record_operation.RecordOperationCommand import (
            RecordOperationCommand,
        )
        from aef_domain.contexts.sessions.slices.start_session.StartSessionCommand import (
            StartSessionCommand,
        )

        # Step 1: Start session
        aggregate = AgentSessionAggregate()
        aggregate._handle_command(
            StartSessionCommand(
                aggregate_id=unique_session_id,
                workflow_id="workflow-lifecycle",
                execution_id="exec-lifecycle",
                phase_id="phase-main",
                milestone_id="milestone-1",
                agent_provider="anthropic",
                agent_model="claude-sonnet-4-20250514",
                metadata={"environment": "test"},
            )
        )
        await agent_session_repository.save(aggregate)

        # Step 2: Initial request
        loaded = await agent_session_repository.load(unique_session_id)
        assert loaded is not None
        loaded._handle_command(
            RecordOperationCommand(
                aggregate_id=unique_session_id,
                operation_type="message_request",
                input_tokens=2000,
                output_tokens=1000,
                total_tokens=3000,
                duration_seconds=3.0,
            )
        )
        await agent_session_repository.save(loaded)

        # Step 3: Tool execution
        loaded = await agent_session_repository.load(unique_session_id)
        assert loaded is not None
        loaded._handle_command(
            RecordOperationCommand(
                aggregate_id=unique_session_id,
                operation_type="tool_execution",
                input_tokens=500,
                output_tokens=200,
                total_tokens=700,
                duration_seconds=1.5,
                tool_name="Read",
                success=True,
            )
        )
        await agent_session_repository.save(loaded)

        # Step 4: Complete session
        loaded = await agent_session_repository.load(unique_session_id)
        assert loaded is not None
        loaded._handle_command(
            CompleteSessionCommand(
                aggregate_id=unique_session_id,
                success=True,
                final_artifact_id="artifact-output",
            )
        )
        await agent_session_repository.save(loaded)

        # Final verification: Load and verify all state
        final = await agent_session_repository.load(unique_session_id)

        assert final is not None
        assert final.id == unique_session_id
        assert final.workflow_id == "workflow-lifecycle"
        assert final._phase_id == "phase-main"
        assert final.status == SessionStatus.COMPLETED
        assert final.tokens.input_tokens == 2500
        assert final.tokens.output_tokens == 1200
        assert final.tokens.total_tokens == 3700
        assert final.operation_count == 2
        assert final.version == 4  # 1 start + 2 operations + 1 complete
