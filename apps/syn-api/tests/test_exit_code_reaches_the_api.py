"""#1319: a client can read what a failed phase exited with, not just that it did.

`status: failed` says the phase did not succeed. It does not say whether the
phase reached its time budget (124, so the work is unfinished and should be
CONTINUED) or was killed outright (-11, so it should be RETRIED), and those
call for opposite handling. Until this field the number existed only inside the
prose of `error_message`, where a client can only find it by parsing a sentence
that was never a contract.

These pin BOTH mapping hops. Each one re-lists every field by hand, and
`_map_phase_to_response` carries a comment naming itself as the hop that has
dropped a field twice already (#891, #1176) - a status declared at both ends
and lost in the middle is exactly how those shipped.
"""

from __future__ import annotations

import pytest

from syn_api.routes.executions.queries import _map_phase_detail, _map_phase_to_response
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
)

pytestmark = pytest.mark.unit

#: A SIGSEGV kill (#1295). Negative, so it cannot be produced by a default, by
#: a truthiness slip, or by a status inferred from `status == "failed"`; its
#: appearance at the wire could only be the number carried through both hops.
SEGFAULTED = -11

#: The phase reached its time budget. Distinct from -11 in what it asks the
#: client to DO, which is the entire reason the field is an int and not a flag.
TIMED_OUT = 124


def _failed_phase(exit_code: int | None) -> PhaseExecutionDetail:
    return PhaseExecutionDetail(
        workflow_phase_id="implement",
        name="Implement",
        status="failed",
        session_id=None,
        error_message="Agent execution failed for phase implement",
        exit_code=exit_code,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("exit_code", [SEGFAULTED, TIMED_OUT])
async def test_the_status_survives_the_read_model_to_api_hop(exit_code: int) -> None:
    """Hop 1: read model -> PhaseExecution."""
    mapped = await _map_phase_detail(_failed_phase(exit_code), None, {})

    assert mapped.exit_code == exit_code


@pytest.mark.anyio
@pytest.mark.parametrize("exit_code", [SEGFAULTED, TIMED_OUT])
async def test_the_status_survives_the_hop_to_the_response_model(exit_code: int) -> None:
    """Hop 2: PhaseExecution -> the HTTP response an operator actually reads."""
    response = _map_phase_to_response(await _map_phase_detail(_failed_phase(exit_code), None, {}))

    assert response.exit_code == exit_code


@pytest.mark.anyio
async def test_a_phase_nobody_watched_reports_null_not_zero() -> None:
    """The three-valued contract, at the boundary that has to keep it.

    `null` means nothing observed a status - a phase stranded by an API
    restart, an execution predating the field. Coercing it to 0 here would tell
    a client the phase exited cleanly, which is the opposite of what happened
    and the one reading that is worse than no reading at all.
    """
    response = _map_phase_to_response(await _map_phase_detail(_failed_phase(None), None, {}))

    assert response.exit_code is None
