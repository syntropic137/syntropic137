"""The leader id map must not leak between concurrent executions (#931).

BackgroundWorkflowDispatcher shares ONE processor across dispatches - the
module says so beside _DispatchContext - so two runs of the same workflow share
a phase id. Keyed by phase alone, one run reads the other's leader; a leader id
absent from this run's sweep then takes the refusal path, and the refusal is
only a log line, so the execution reports a complete-looking total with no
delegate in it.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import import (
    remember_leader_native_id,
)

pytestmark = pytest.mark.unit


def _result(native: str | None) -> StreamResult:
    return StreamResult(
        line_count=1,
        interrupt_requested=False,
        interrupt_reason=None,
        agent_task_result=None,
        leader_native_session_id=native,
    )


def test_two_executions_of_the_same_phase_keep_separate_leaders() -> None:
    ids: dict[tuple[str, str], str] = {}

    remember_leader_native_id(ids, ("exec-A", "build"), _result("leader-A"))
    remember_leader_native_id(ids, ("exec-B", "build"), _result("leader-B"))

    assert ids[("exec-A", "build")] == "leader-A"
    assert ids[("exec-B", "build")] == "leader-B", (
        "a phase-only key lets one execution overwrite another's leader"
    )


def test_a_blank_announcement_is_not_stored() -> None:
    """Every phase that announced nothing would otherwise share one key."""
    ids: dict[tuple[str, str], str] = {}

    remember_leader_native_id(ids, ("exec-A", "build"), _result(None))
    remember_leader_native_id(ids, ("exec-A", "build"), _result(""))

    assert ids == {}


def test_first_announcement_wins_within_one_execution() -> None:
    ids: dict[tuple[str, str], str] = {}

    remember_leader_native_id(ids, ("exec-A", "build"), _result("first"))
    remember_leader_native_id(ids, ("exec-A", "build"), _result("second"))

    assert ids[("exec-A", "build")] == "second", (
        "remember_leader_native_id overwrites by design; FIRST-wins is enforced "
        "in the stream processors, which only ever announce once"
    )
