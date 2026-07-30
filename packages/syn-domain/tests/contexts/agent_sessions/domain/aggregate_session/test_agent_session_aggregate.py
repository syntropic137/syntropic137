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


def test_start_session_with_parent_and_no_root_defaults_root_to_parent() -> None:
    """Regression guard (#792): a delegated child must never self-root.

    When only parent_session_id is supplied (no root_session_id), the child's
    root must default to the parent, NOT to the child's own id. Defaulting to
    self would silently produce a malformed tree where a delegated session
    claims to be its own root.
    """
    aggregate = AgentSessionAggregate()
    command = StartSessionCommand(
        aggregate_id="child-2",
        workflow_id="wf-1",
        phase_id="phase-1",
        agent_provider="claude",
        parent_session_id="parent-2",
    )

    aggregate.start_session(command)

    event = aggregate.get_uncommitted_events()[-1].event
    assert event.parent_session_id == "parent-2"
    assert event.root_session_id == "parent-2"


def test_start_session_with_parent_and_explicit_root_uses_explicit_root() -> None:
    """An explicitly supplied root_session_id always wins, even with a parent set.

    Lets a caller that knows the true root of a deeper (3+ level) tree pass it
    explicitly, rather than being forced into a two-level assumption.
    """
    aggregate = AgentSessionAggregate()
    command = StartSessionCommand(
        aggregate_id="child-3",
        workflow_id="wf-1",
        phase_id="phase-1",
        agent_provider="claude",
        parent_session_id="parent-3",
        root_session_id="root-of-deep-tree",
    )

    aggregate.start_session(command)

    event = aggregate.get_uncommitted_events()[-1].event
    assert event.parent_session_id == "parent-3"
    assert event.root_session_id == "root-of-deep-tree"


def test_start_session_without_parent_and_explicit_root_uses_explicit_root() -> None:
    """An explicitly supplied root_session_id wins even for a top-level session."""
    aggregate = AgentSessionAggregate()
    command = StartSessionCommand(
        aggregate_id="session-4",
        workflow_id="wf-1",
        phase_id="phase-1",
        agent_provider="claude",
        root_session_id="explicit-root-4",
    )

    aggregate.start_session(command)

    event = aggregate.get_uncommitted_events()[-1].event
    assert event.parent_session_id is None
    assert event.root_session_id == "explicit-root-4"
