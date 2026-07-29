"""Unit tests for AgentSessionAggregate.start_session parent/root linkage (#792)."""

from __future__ import annotations

from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)


def test_start_session_without_parent_is_its_own_root() -> None:
    """A top-level session (no parent_session_id) is its own root."""
    aggregate = AgentSessionAggregate()
    command = StartSessionCommand(
        aggregate_id="session-1",
        workflow_id="wf-1",
        phase_id="phase-1",
        agent_provider="claude",
    )

    aggregate.start_session(command)

    event = aggregate.get_uncommitted_events()[-1].event
    assert event.parent_session_id is None
    assert event.root_session_id == "session-1"


def test_start_session_with_parent_threads_both_ids() -> None:
    """A delegated child session carries parent_session_id and root_session_id."""
    aggregate = AgentSessionAggregate()
    command = StartSessionCommand(
        aggregate_id="child-1",
        workflow_id="wf-1",
        phase_id="phase-1",
        agent_provider="claude",
        parent_session_id="parent-1",
        root_session_id="root-1",
    )

    aggregate.start_session(command)

    event = aggregate.get_uncommitted_events()[-1].event
    assert event.parent_session_id == "parent-1"
    assert event.root_session_id == "root-1"
