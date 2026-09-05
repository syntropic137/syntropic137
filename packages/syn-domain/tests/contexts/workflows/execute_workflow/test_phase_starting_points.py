"""The lifecycle the processor no longer spells out for itself (#1200, #1203).

Where a failing phase's branches stand needs a reading taken at provision and
read at failure, and the processor used to hold that map itself: it knew there
was a dict, what was in it, and which of four moments it was in. `record` /
`observe` / `forget` / `forget_all` moved that knowledge into
`PhaseStartingPoints`, and these pin the two halves a relocation can silently
get wrong - dropping a starting point too late, or dropping too many at once.

They drive the processor's real `_finalize_phase` and
`_close_phase_workspace_cms` rather than the registry directly, because those
two are the callers whose choice of `forget` over `forget_all` is the thing
under test. Calling `forget_all` from `_finalize_phase` would leave every
concurrently running phase unable to say where its branches stood, and every
assertion about a single-phase failure would still pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    PhaseStartingPoint,
    PhaseStartingPoints,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
        GitWorkspace,
    )

pytestmark = pytest.mark.unit

_DONE = "implement"
_STILL_RUNNING = "verify"


def _a_starting_point() -> PhaseStartingPoint:
    """A reading whose contents no assertion here depends on.

    These tests are about WHICH phase's reading survives, never about what any
    reading says - that is `test_branch_state_is_reported.py`'s subject, and it
    needs a real git workspace to say anything true.
    """
    return PhaseStartingPoint(workspace=cast("GitWorkspace", object()), remote_refs={})


def _processor_holding_two_phases() -> WorkflowExecutionProcessor:
    """A processor mid-execution with two phases open, built without its graph.

    `_finalize_phase` and `_close_phase_workspace_cms` touch a known, small set
    of attributes; the real constructor would drag in a workspace service and
    repositories that have nothing to do with which starting points survive.
    Every port is None so that capture, delegate import and teardown are all
    no-ops and cannot mask the one thing being asserted.
    """
    p = object.__new__(WorkflowExecutionProcessor)
    p._session_managers = {}  # type: ignore[attr-defined]
    p._active_workspaces = {}  # type: ignore[attr-defined]
    p._phase_session_ids = {}  # type: ignore[attr-defined]
    p._active_envs = {}  # type: ignore[attr-defined]
    p._active_cmds = {}  # type: ignore[attr-defined]
    p._active_workspace_cms = {}  # type: ignore[attr-defined]
    p._session_capture = None  # type: ignore[attr-defined]
    p._session_store = None  # type: ignore[attr-defined]
    p._observability_writer = None  # type: ignore[attr-defined]
    p._phase_leader_native_ids = {}  # type: ignore[attr-defined]
    p._import_ledger = None  # type: ignore[attr-defined]

    points = PhaseStartingPoints()
    points._by_phase[_DONE] = _a_starting_point()
    points._by_phase[_STILL_RUNNING] = _a_starting_point()
    p._phase_starting_points = points  # type: ignore[attr-defined]
    return p


async def test_a_finishing_phase_forgets_its_own_starting_point_and_no_others() -> None:
    """One phase ending must not blind the phases still running.

    The pairing that has to survive is phase-to-workspace: a starting point
    from one phase compared against another phase's workspace produces a
    confident, wrong answer about where work went. Both failure modes are
    silent - forgetting too much makes a later failure say "nobody looked",
    which is a legitimate answer no assertion elsewhere would question.
    """
    processor = _processor_holding_two_phases()

    await processor._finalize_phase(  # pyright: ignore[reportPrivateUsage]
        _DONE,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=0,
        duration=1.0,
    )

    held = set(processor._phase_starting_points._by_phase)  # pyright: ignore[reportPrivateUsage]
    assert held == {_STILL_RUNNING}, (
        "finalising one phase must forget exactly that phase's starting point; "
        f"the registry now holds {held}"
    )


async def test_a_dying_execution_forgets_every_phase_it_was_still_holding() -> None:
    """The other way a workspace goes away, and it takes all of them.

    The terminal paths close every workspace still open, so every starting
    point they were paired with describes a container that no longer exists.
    Keeping one would outlive its workspace on a long-lived processor, and the
    next execution to reuse the phase id would be answered from it.
    """
    processor = _processor_holding_two_phases()

    await processor._close_phase_workspace_cms(  # pyright: ignore[reportPrivateUsage]
        context="failure"
    )

    held = set(processor._phase_starting_points._by_phase)  # pyright: ignore[reportPrivateUsage]
    assert not held, f"starting points outlived the workspaces they describe: {held}"
