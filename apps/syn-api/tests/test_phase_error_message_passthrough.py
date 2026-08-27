"""#891: a failed phase must report WHY it failed, not error_message: null.

The reason already existed at both ends of the chain: the get_execution_detail
projection writes ``error_message`` onto the failed phase record, and the HTTP
model ``PhaseExecutionInfo`` already declared the field. The intermediate API
model ``PhaseExecution`` did not, so both mappers silently dropped it and every
failed phase surfaced ``error_message: null``.

These tests pin BOTH hops, because either one alone re-opens the hole.
"""

from __future__ import annotations

import pytest

from syn_api.routes.executions.queries import _map_phase_detail, _map_phase_to_response
from syn_api.types import PhaseExecution
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
)

pytestmark = pytest.mark.unit

_REASON = "Authentication failed (HTTP 401): codex CLI login - Failed to refresh token"


def _failed_phase_detail() -> PhaseExecutionDetail:
    return PhaseExecutionDetail(
        workflow_phase_id="p-1",
        name="Review",
        status="failed",
        session_id=None,
        error_message=_REASON,
    )


@pytest.mark.anyio
async def test_read_model_error_message_reaches_the_api_model() -> None:
    """Hop 1: read model -> PhaseExecution."""
    mapped = await _map_phase_detail(_failed_phase_detail(), None)

    assert mapped.error_message == _REASON


@pytest.mark.anyio
async def test_api_model_error_message_reaches_the_http_response() -> None:
    """Hop 2: PhaseExecution -> PhaseExecutionInfo."""
    phase = PhaseExecution(
        phase_id="p-1",
        name="Review",
        status="failed",
        error_message=_REASON,
    )

    response = _map_phase_to_response(phase)

    assert response.error_message == _REASON


@pytest.mark.anyio
async def test_a_successful_phase_carries_no_error_message() -> None:
    detail = PhaseExecutionDetail(
        workflow_phase_id="p-1",
        name="Review",
        status="completed",
        session_id=None,
    )

    mapped = await _map_phase_detail(detail, None)

    assert mapped.error_message is None
    assert _map_phase_to_response(mapped).error_message is None
