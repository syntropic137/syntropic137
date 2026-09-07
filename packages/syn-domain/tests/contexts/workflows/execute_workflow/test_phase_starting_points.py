"""The lifecycle the processor no longer spells out for itself (#1200, #1203).

Where a failing phase's branches stand needs a reading taken at provision and
read at failure, and the processor used to hold that map itself: it knew there
was a dict, what was in it, and which of four moments it was in. `record` /
`observe` / `forget` / `forget_all` moved that knowledge into
`PhaseStartingPoints`, and these pin the two halves a relocation can silently
get wrong - dropping a starting point too late, or dropping too many at once.

They drive the real `PhaseRuntime.finalize` and `PhaseRuntime.abandon_all`
rather than the registry directly, because those two are the callers whose
choice of `forget` over `forget_all` is the thing under test. Calling
`forget_all` from `finalize` would leave every concurrently running phase
unable to say where its branches stood, and every assertion about a
single-phase failure would still pass.

Those two callers used to be the processor's own `_finalize_phase` and
`_close_phase_workspace_cms`; #1203 moved the per-phase state and both
lifecycle steps into `PhaseRuntime` unchanged. The subject is the same
choice, asked of whoever now makes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    PhaseStartingPoint,
    PhaseStartingPoints,
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


def _runtime_holding_two_phases() -> PhaseRuntime:
    """A runtime mid-execution with two phases open and nothing else.

    Every port is None so that capture, delegate import and teardown are all
    no-ops and cannot mask the one thing being asserted. Neither phase holds a
    workspace: `finalize` and `abandon_all` both tolerate that, and a fake one
    would only add a way for these tests to fail for an unrelated reason.
    """
    points = PhaseStartingPoints()
    points._by_phase[_DONE] = _a_starting_point()
    points._by_phase[_STILL_RUNNING] = _a_starting_point()
    return PhaseRuntime(
        capture_port=None,
        session_store=None,
        writer=None,
        ledger=None,
        starting_points=points,
    )


async def test_a_finishing_phase_forgets_its_own_starting_point_and_no_others() -> None:
    """One phase ending must not blind the phases still running.

    The pairing that has to survive is phase-to-workspace: a starting point
    from one phase compared against another phase's workspace produces a
    confident, wrong answer about where work went. Both failure modes are
    silent - forgetting too much makes a later failure say "nobody looked",
    which is a legitimate answer no assertion elsewhere would question.
    """
    runtime = _runtime_holding_two_phases()

    await runtime.finalize(
        _DONE,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        total_tokens=0,
        duration_seconds=1.0,
    )

    held = set(runtime._starting_points._by_phase)  # pyright: ignore[reportPrivateUsage]
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
    runtime = _runtime_holding_two_phases()

    await runtime.abandon_all(context="failure")

    held = set(runtime._starting_points._by_phase)  # pyright: ignore[reportPrivateUsage]
    assert not held, f"starting points outlived the workspaces they describe: {held}"
