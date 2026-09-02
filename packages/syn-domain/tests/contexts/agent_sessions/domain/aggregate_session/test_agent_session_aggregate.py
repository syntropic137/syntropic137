"""Unit tests for AgentSessionAggregate.start_session parent/root linkage (#792)."""

from __future__ import annotations

import pytest

from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
    AgentSessionAggregate,
)
from syn_domain.contexts.agent_sessions.domain.commands.MarkAgentLaunchedCommand import (
    MarkAgentLaunchedCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
    StartSessionCommand,
)


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
def test_agent_launched_defaults_false_before_any_command() -> None:
    """A freshly constructed aggregate has agent_launched=False - the
    baseline the never-started detection relies on (#1047, #1065).
    """
    aggregate = AgentSessionAggregate()
    assert aggregate.agent_launched is False


@pytest.mark.unit
def test_mark_agent_launched_flips_the_flag() -> None:
    """mark_agent_launched sets agent_launched=True, the sole discriminator
    between "no agent ever ran" and "an agent ran and later failed" - both
    leave total_tokens at 0 on the failure path (#1047, #1065).
    """
    aggregate = AgentSessionAggregate()
    aggregate.start_session(
        StartSessionCommand(
            aggregate_id="session-launch-1",
            workflow_id="wf-1",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )

    aggregate.mark_agent_launched(MarkAgentLaunchedCommand(aggregate_id="session-launch-1"))

    assert aggregate.agent_launched is True


@pytest.mark.unit
def test_mark_agent_launched_is_idempotent() -> None:
    """A second mark_agent_launched call is a no-op, not an error or a
    duplicate event - the fact "the agent launched" is true regardless of how
    many times it's reported, unlike record_operation/complete_session which
    do enforce invariants that a repeat call could violate.
    """
    aggregate = AgentSessionAggregate()
    aggregate.start_session(
        StartSessionCommand(
            aggregate_id="session-launch-2",
            workflow_id="wf-1",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )

    aggregate.mark_agent_launched(MarkAgentLaunchedCommand(aggregate_id="session-launch-2"))
    events_after_first = len(aggregate.get_uncommitted_events())

    aggregate.mark_agent_launched(MarkAgentLaunchedCommand(aggregate_id="session-launch-2"))
    events_after_second = len(aggregate.get_uncommitted_events())

    assert aggregate.agent_launched is True
    assert events_after_second == events_after_first
