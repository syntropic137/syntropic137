"""#1200: an API client can tell "we know where it went" from "we don't".

The domain records three states for a failed phase - locations confirmed on a
remote, `()` for "we asked and none of this phase's work is on one", and None
for "nobody could ask". Two of them read the same in prose, so the difference
only survives as structure. These pin BOTH mapping hops, because either one
dropping the field puts the client back to reading sentences: that is exactly
how #891 shipped, with the field declared at both ends and lost in the middle.
"""

from __future__ import annotations

import pytest

from syn_api.routes.executions.queries import _map_phase_detail, _map_phase_to_response
from syn_api.types import PhaseExecution, PushedWorkInfo
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PushedWork,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
)

pytestmark = pytest.mark.unit

_BRANCH = "fix/1187-open-pr-bootstrap-overhead"
_COMMIT = "9f2c1a4e6b7d8c0f1e2a3b4c5d6e7f8091a2b3c4"
_PUSHED = PushedWork(repo="syntropic137", branch=_BRANCH, commit=_COMMIT)


def _failed_phase(pushed_work: tuple[PushedWork, ...] | None) -> PhaseExecutionDetail:
    return PhaseExecutionDetail(
        workflow_phase_id="implement",
        name="Implement",
        status="failed",
        session_id=None,
        error_message="the phase produced none of its declared output",
        pushed_work=pushed_work,
    )


@pytest.mark.anyio
async def test_a_pushed_branch_reaches_the_api_model() -> None:
    """Hop 1: read model -> PhaseExecution."""
    mapped = await _map_phase_detail(_failed_phase((_PUSHED,)), None, {})

    assert mapped.pushed_work == [
        PushedWorkInfo(repo="syntropic137", branch=_BRANCH, commit=_COMMIT)
    ]


@pytest.mark.anyio
async def test_a_pushed_branch_reaches_the_http_response() -> None:
    """Hop 2: PhaseExecution -> PhaseExecutionInfo, which is what is served."""
    phase = PhaseExecution(
        phase_id="implement",
        name="Implement",
        status="failed",
        pushed_work=[PushedWorkInfo(repo="syntropic137", branch=_BRANCH, commit=_COMMIT)],
    )

    response = _map_phase_to_response(phase)

    assert response.pushed_work is not None
    assert [(w.branch, w.commit) for w in response.pushed_work] == [(_BRANCH, _COMMIT)]


@pytest.mark.anyio
async def test_asked_and_nothing_is_not_the_same_value_as_nobody_asked() -> None:
    """The distinction (c) is about, made at the boundary a client reads.

    Empty list: git was asked and none of this phase's work is on a remote, so
    there is nothing to recover and no point looking. Null: the workspace could
    not answer, so work MAY be out there and a human should go and check. A
    client that has to grep an error string cannot act differently on those.
    """
    asked = await _map_phase_detail(_failed_phase(()), None, {})
    unknown = await _map_phase_detail(_failed_phase(None), None, {})

    assert asked.pushed_work == []
    assert unknown.pushed_work is None
    assert _map_phase_to_response(asked).pushed_work == []
    assert _map_phase_to_response(unknown).pushed_work is None


@pytest.mark.anyio
async def test_a_phase_that_did_not_fail_carries_nothing() -> None:
    """(d) at this layer: the success path is untouched and stays null."""
    completed = PhaseExecutionDetail(
        workflow_phase_id="implement",
        name="Implement",
        status="completed",
        session_id=None,
    )

    mapped = await _map_phase_detail(completed, None, {})

    assert mapped.pushed_work is None
    assert _map_phase_to_response(mapped).pushed_work is None
