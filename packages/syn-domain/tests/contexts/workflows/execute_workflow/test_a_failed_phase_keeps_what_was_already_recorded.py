"""#1262: failing a phase must not erase what the run had already recorded on it.

WHY THIS EXISTS. The failure path now applies the WorkflowFailed event to the
phase through `PhaseDetail` - it hydrates the stored phase, stamps the failure
onto the model, and writes the model back. That is what lets the stamping be
done by attribute instead of by string key, and it is also a new way to lose a
field: anything in the stored phase that `PhaseDetail` does not declare is
dropped on the way back out, silently, on every failed phase.

It was already one field short when this was written. The failure path had been
writing `observed_branches` into the phase dict while `PhaseDetail` did not name
it (#1200), so the round-trip would have deleted the branch readings at the
exact moment they matter - a phase that died. Nothing round-tripped a phase
before, so nothing was losing it yet; the model was one refactor away from a
silent data loss and this is the refactor.

WHAT IT ASSERTS, AND WHY THOSE FIELDS. Two groups, and the second is the point:

  - what the FAILURE carries - the tokens, the duration, the branches. These
    are #1262's own signals and are asserted at the read model the API serves.
  - what was recorded BEFORE the failure - the session id, the start time, the
    phase name and the BUDGET. None of these appear on the failure event at
    all, so they can only survive by surviving the round-trip. `timeout_seconds`
    is the sharpest of them: it is stated once on WorkflowExecutionStarted and
    is the denominator of "elapsed against the budget", so a phase that loses it
    reports an exit 124 with nothing to read it against - which is the state
    #1262 began in.

THE FIXTURES CANNOT ARISE FROM A DEFAULT. Every token field defaults to 0 and
every other field to None or "", so a hop that drops one reports the default and
fails here rather than coincidentally agreeing. The token counts are the
incident's own: 190 in, 545 out, 13 cache-write, 27 cache-read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.get_execution_detail.phase_detail import (
    PhaseDetail,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        PhaseExecutionDetail,
    )

pytestmark = pytest.mark.unit

_EXECUTION_ID = "exec-1262-keeps"
_PHASE_ID = "phase-implement"
_SESSION_ID = "sess-1262-keeps"
_STARTED_AT = "2026-09-17T22:14:03+00:00"
_DIED_AT = "2026-09-17T22:34:03+00:00"

#: The budget the run stated, in seconds. Only ever on WorkflowExecutionStarted.
_BUDGET_SECONDS = 1200

#: What the phase had burned when it was killed (the incident's own numbers).
_INPUT_TOKENS = 190
_OUTPUT_TOKENS = 545
_CACHE_CREATION_TOKENS = 13
_CACHE_READ_TOKENS = 27

#: A branch reading, as `model_dump()` hands it to a projection: plain data.
_BRANCH_READING: dict[str, Any] = {
    "repo": "syntropic137",
    "branch": "fix/1262-timeout-vs-stall-signals",
    "remote": "origin",
    "remote_commit": "017e296e",
    "remote_commit_at_phase_start": "9e0223a7",
    "unpushed_commits": 2,
}


async def _failed_phase_as_the_api_reads_it() -> PhaseExecutionDetail:
    """A phase killed on its cap, read back through the model the API serves.

    The run states its budget, the phase starts and records a session, and then
    the workflow FAILS naming that phase - which is the path exit 124 takes.
    There is no PhaseCompleted, by construction, exactly as there is none for a
    real timeout.
    """
    projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())

    await projection.on_workflow_execution_started(
        {
            "execution_id": _EXECUTION_ID,
            "workflow_id": "wf-1262",
            "workflow_name": "sdlc-implement",
            "started_at": _STARTED_AT,
            "total_phases": 1,
            "phase_definitions": [
                {
                    "phase_id": _PHASE_ID,
                    "name": "implement",
                    "order": 0,
                    "timeout_seconds": _BUDGET_SECONDS,
                }
            ],
        }
    )
    await projection.on_phase_started(
        {
            "execution_id": _EXECUTION_ID,
            "phase_id": _PHASE_ID,
            "phase_name": "implement",
            "session_id": _SESSION_ID,
            "started_at": _STARTED_AT,
        }
    )
    await projection.on_workflow_failed(
        {
            "execution_id": _EXECUTION_ID,
            "workflow_id": "wf-1262",
            "failed_at": _DIED_AT,
            "failed_phase_id": _PHASE_ID,
            "error_message": "Agent process exited with code 124",
            "failed_phase_duration_seconds": 1200.0,
            "failed_phase_input_tokens": _INPUT_TOKENS,
            "failed_phase_output_tokens": _OUTPUT_TOKENS,
            "failed_phase_cache_creation_tokens": _CACHE_CREATION_TOKENS,
            "failed_phase_cache_read_tokens": _CACHE_READ_TOKENS,
            "failed_phase_artifact_ids": ["artifact-implement-md"],
            "observed_branches": [_BRANCH_READING],
        }
    )

    execution = await projection.get_by_id(_EXECUTION_ID)
    assert execution is not None, "the projection must have stored the execution"
    return next(p for p in execution.phases if p.workflow_phase_id == _PHASE_ID)


@pytest.mark.anyio
async def test_the_budget_survives_the_phase_being_failed() -> None:
    """The denominator of "elapsed against the budget", recorded 20 minutes earlier.

    `timeout_seconds` is never on the failure event. It reaches this phase from
    WorkflowExecutionStarted and has to still be there afterwards, or an exit
    124 arrives with nothing to measure it against.
    """
    phase = await _failed_phase_as_the_api_reads_it()

    assert phase.timeout_seconds == _BUDGET_SECONDS
    assert phase.duration_seconds == 1200.0, "the elapsed time it is read against"


@pytest.mark.anyio
async def test_what_the_phase_spent_reaches_the_read_model() -> None:
    """The counts that separate a stall from a phase that needed more room."""
    phase = await _failed_phase_as_the_api_reads_it()

    assert phase.input_tokens == _INPUT_TOKENS
    assert phase.output_tokens == _OUTPUT_TOKENS
    assert phase.cache_creation_tokens == _CACHE_CREATION_TOKENS
    assert phase.cache_read_tokens == _CACHE_READ_TOKENS
    assert phase.total_tokens == (
        _INPUT_TOKENS + _OUTPUT_TOKENS + _CACHE_CREATION_TOKENS + _CACHE_READ_TOKENS
    ), "summed from the four, so it cannot disagree with them"


@pytest.mark.anyio
async def test_the_branch_readings_survive_the_phase_being_failed() -> None:
    """The field `PhaseDetail` did not declare, on the one path that writes it.

    Three-valued and asserted as such: this is a READING, not the `()` that
    means the workspace was read and nothing had moved, and not the `None` that
    means nothing could look (#1200).
    """
    phase = await _failed_phase_as_the_api_reads_it()

    assert phase.observed_branches is not None, "None here would read as 'nobody looked'"
    assert len(phase.observed_branches) == 1
    reading = phase.observed_branches[0]
    assert reading.branch == _BRANCH_READING["branch"]
    assert reading.unpushed_commits == 2


@pytest.mark.anyio
async def test_the_phase_still_knows_who_ran_it_and_when() -> None:
    """Identity recorded at PhaseStarted, absent from the failure event entirely.

    A failed phase whose session id is gone is a phase whose transcript, tools
    and cost rows nothing can be joined to - which is the only other way left
    to tell a stall from a timeout once the counts are missing.
    """
    phase = await _failed_phase_as_the_api_reads_it()

    assert phase.session_id == _SESSION_ID
    assert phase.started_at == _STARTED_AT
    assert phase.name == "implement"
    assert phase.status == "failed"
    assert phase.artifact_id == "artifact-implement-md"


@pytest.mark.anyio
async def test_a_stored_phase_survives_being_read_back_and_written_out() -> None:
    """`from_dict` and `to_dict` are inverses, which is what the round-trip assumes.

    The tests above drive the failure path, and on that path every field the
    round-trip could lose is immediately overwritten from the event - so they
    pin the serializer and cannot pin the constructor. This one pins the pair
    directly: read a stored phase and write it straight back out, and nothing
    may change.

    Stated as an equality over the whole dict rather than field by field, so a
    field added to `PhaseDetail` tomorrow and forgotten in one of the two
    halves fails here instead of going quiet.
    """
    stored = PhaseDetail(
        phase_id=_PHASE_ID,
        name="implement",
        status="failed",
        session_id=_SESSION_ID,
        artifact_id="artifact-implement-md",
        input_tokens=_INPUT_TOKENS,
        output_tokens=_OUTPUT_TOKENS,
        cache_creation_tokens=_CACHE_CREATION_TOKENS,
        cache_read_tokens=_CACHE_READ_TOKENS,
        total_tokens=775,
        duration_seconds=1200.0,
        started_at=_STARTED_AT,
        completed_at=_DIED_AT,
        timeout_seconds=_BUDGET_SECONDS,
        error_message="Agent process exited with code 124",
        observed_branches=[_BRANCH_READING],
        deliverable_recovered=True,
    ).to_dict()

    assert PhaseDetail.from_dict(stored).to_dict() == stored
