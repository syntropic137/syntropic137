"""Tests for event type consistency between agentic_events and syn_shared.

These tests are a POKA-YOKE (mistake-proofing) mechanism that catches
producer/consumer event type drift at CI time rather than in production.

The problem this solves:
    - agentic_events.types.EventType (in agentic-primitives) defines what
      the hook producer actually emits.
    - syn_shared.events.VALID_EVENT_TYPES defines what the consumer
      (WorkflowExecutionEngine, SessionToolsProjection) expects.
    - If these diverge, events are silently dropped or stored under wrong names.

If a test here fails, it means:
    1. A new event type was added to agentic-primitives but not to syn_shared.events
    2. An event type was renamed in one place but not the other
    3. The Literal union in syn_shared.events is out of date

To fix a failure:
    1. Add the missing/renamed constant to syn_shared/events/__init__.py
    2. Add it to the VALID_EVENT_TYPES Literal union
    3. Add the constant to __all__
"""


class TestEventTypeConsistency:
    """Verify event type registries are in sync across packages."""

    def test_every_agentic_events_type_is_in_valid_event_types(self) -> None:
        """Every EventType in agentic_events MUST exist in syn_shared VALID_EVENT_TYPES.

        This is the critical CI gate: if agentic-primitives adds a new event type
        and syn_shared.events is not updated, this test fails before production does.
        """
        from agentic_events.types import EventType

        from syn_shared.events import VALID_EVENT_TYPES

        missing = []
        for member in EventType:
            if member.value not in VALID_EVENT_TYPES:
                missing.append(f"  EventType.{member.name} = {member.value!r}")

        assert not missing, (
            "The following agentic_events.EventType values are NOT in "
            "syn_shared.events.VALID_EVENT_TYPES.\n"
            "Add them to packages/syn-shared/src/syn_shared/events/__init__.py:\n"
            + "\n".join(missing)
        )

    def test_valid_event_types_matches_literal_union(self) -> None:
        """VALID_EVENT_TYPES must be derived from the Literal union, not a separate list.

        This is guaranteed by the construction:
            VALID_EVENT_TYPES: set[str] = set(get_args(EventType))
        but this test makes the invariant explicit and visible.
        """
        from typing import get_args

        from syn_shared.events import VALID_EVENT_TYPES
        from syn_shared.events import EventType as SynEventType

        literal_values = set(get_args(SynEventType))
        assert literal_values == VALID_EVENT_TYPES, (
            "VALID_EVENT_TYPES and the EventType Literal union are out of sync in syn_shared.events. "
            f"In Literal but not in set: {literal_values - VALID_EVENT_TYPES!r}. "
            f"In set but not in Literal: {VALID_EVENT_TYPES - literal_values!r}."
        )

    def test_syn_shared_constants_match_their_literal_values(self) -> None:
        """Each named constant in syn_shared.events must match the Literal.

        This catches mistakes like defining TOOL_EXECUTION_STARTED = "tool_started" while
        the Literal says "tool_execution_started".
        """
        from syn_shared.events import (
            AGENT_STOPPED,
            CONTEXT_COMPACTED,
            COST_RECORDED,
            ERROR,
            GIT_BRANCH_CHANGED,
            GIT_COMMIT,
            GIT_OPERATION,
            GIT_PUSH,
            SYSTEM_NOTIFICATION,
            PERMISSION_REQUESTED,
            PHASE_COMPLETED,
            PHASE_STARTED,
            USER_PROMPT_SUBMITTED,
            SECURITY_DECISION,
            SESSION_COMPLETED,
            SESSION_ERROR,
            SESSION_STARTED,
            SESSION_SUMMARY,
            SUBAGENT_STARTED,
            SUBAGENT_STOPPED,
            TASK_COMPLETED,
            TEAMMATE_IDLE,
            TOKEN_USAGE,
            TOOL_BLOCKED,
            TOOL_EXECUTION_COMPLETED,
            TOOL_EXECUTION_FAILED,
            TOOL_EXECUTION_STARTED,
            VALID_EVENT_TYPES,
        )

        all_constants = {
            "AGENT_STOPPED": AGENT_STOPPED,
            "CONTEXT_COMPACTED": CONTEXT_COMPACTED,
            "COST_RECORDED": COST_RECORDED,
            "ERROR": ERROR,
            "GIT_BRANCH_CHANGED": GIT_BRANCH_CHANGED,
            "GIT_COMMIT": GIT_COMMIT,
            "GIT_OPERATION": GIT_OPERATION,
            "GIT_PUSH": GIT_PUSH,
            "SYSTEM_NOTIFICATION": SYSTEM_NOTIFICATION,
            "PERMISSION_REQUESTED": PERMISSION_REQUESTED,
            "PHASE_COMPLETED": PHASE_COMPLETED,
            "PHASE_STARTED": PHASE_STARTED,
            "USER_PROMPT_SUBMITTED": USER_PROMPT_SUBMITTED,
            "SECURITY_DECISION": SECURITY_DECISION,
            "SESSION_COMPLETED": SESSION_COMPLETED,
            "SESSION_ERROR": SESSION_ERROR,
            "SESSION_STARTED": SESSION_STARTED,
            "SESSION_SUMMARY": SESSION_SUMMARY,
            "SUBAGENT_STARTED": SUBAGENT_STARTED,
            "SUBAGENT_STOPPED": SUBAGENT_STOPPED,
            "TASK_COMPLETED": TASK_COMPLETED,
            "TEAMMATE_IDLE": TEAMMATE_IDLE,
            "TOKEN_USAGE": TOKEN_USAGE,
            "TOOL_BLOCKED": TOOL_BLOCKED,
            "TOOL_EXECUTION_COMPLETED": TOOL_EXECUTION_COMPLETED,
            "TOOL_EXECUTION_FAILED": TOOL_EXECUTION_FAILED,
            "TOOL_EXECUTION_STARTED": TOOL_EXECUTION_STARTED,
        }

        bad_constants = []
        for name, value in all_constants.items():
            if value not in VALID_EVENT_TYPES:
                bad_constants.append(f"  {name} = {value!r}")

        assert not bad_constants, (
            "The following syn_shared.events constants have values NOT in VALID_EVENT_TYPES.\n"
            "The constant value must exactly match one of the Literal strings:\n"
            + "\n".join(bad_constants)
        )

    def test_observation_type_enum_tool_values_match_syn_shared(self) -> None:
        """ObservationType enum values used in TimescaleDB writes must match syn_shared.events.

        WorkflowExecutionEngine._record_observation() writes to the agent_events
        TimescaleDB table using syn_shared.events constants (EV_TOOL_STARTED,
        EV_TOOL_COMPLETED) — NOT ObservationType enum members — for tool events.

        ObservationType is the domain aggregate type (AgentObservationEvent / event
        sourcing) and its string values for TOOL_EXECUTION_STARTED/TOOL_EXECUTION_COMPLETED intentionally
        differ from the TimescaleDB event types. They are NOT stored directly in
        agent_events; the engine imports syn_shared constants for that.

        This test enforces that the ObservationType members which DO flow through
        both paths (hooks + native CLI) still match syn_shared.events.
        """
        from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
            ObservationType,
        )
        from syn_shared.events import VALID_EVENT_TYPES

        # ALL ObservationType members that are written to agent_events (TimescaleDB)
        # must match syn_shared.events VALID_EVENT_TYPES exactly.
        # If this fails: update the ObservationType value OR add to syn_shared.events.
        must_match = [
            ObservationType.TOKEN_USAGE,
            ObservationType.TOOL_EXECUTION_STARTED,
            ObservationType.TOOL_EXECUTION_COMPLETED,
            ObservationType.TOOL_BLOCKED,
            ObservationType.USER_PROMPT_SUBMITTED,
            ObservationType.SUBAGENT_STARTED,
            ObservationType.SUBAGENT_STOPPED,
            ObservationType.CONTEXT_COMPACTING,
        ]
        for obs in must_match:
            assert obs.value in VALID_EVENT_TYPES, (
                f"ObservationType.{obs.name} = {obs.value!r} is NOT in VALID_EVENT_TYPES. "
                "ObservationType values must match syn_shared.events constants. "
                "Update the ObservationType value in agent_observation.py OR add the "
                "constant to syn_shared/events/__init__.py."
            )
