"""What the API says about an observation that recorded a failure (#1196).

The reproduction was an execution-detail response for a failing verify phase:

    {"operation_type": "session_error",
     "operation_id": "-2026-09-05T02:51:43.414696+00:00",
     "tool_name": "", "tool_use_id": null, "success": true}

Three defects in one row - no reason, a success verdict on an error, and an id
beginning with a hyphen because an absent tool id was concatenated with a
timestamp - and all three are only visible HERE, at the far end of the read
path. The fix is in `syn_adapters.projections.session_tools_verdict`; these
tests assert what a client actually receives, because every previous hop
(#891, #1176) looked correct in isolation while dropping a field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_api.routes.executions.queries import _map_phase_to_response
from syn_api.types import PhaseExecution
from syn_api.types import ToolOperation as ApiToolOperation

if TYPE_CHECKING:
    from syn_api.routes.executions.models import PhaseOperationInfo

WHEN = datetime(2026, 9, 5, 2, 51, 43, 414696, tzinfo=UTC)


async def _operations_over_http(rows: list[dict[str, Any]]) -> list[PhaseOperationInfo]:
    """Every hop a stored observation crosses on its way to a client.

    Timescale row -> SessionToolsProjection -> the adapters dataclass ->
    `syn_api.types.ToolOperation` -> `PhaseOperationInfo`. Asserting on the
    projection alone would pass while the API still dropped the field.
    """
    from syn_adapters.projections.session_tools import SessionToolsProjection

    connection = MagicMock()
    connection.fetch = AsyncMock(return_value=rows)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock())
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
    pool.acquire.return_value.__aexit__ = AsyncMock()

    operations = await SessionToolsProjection(pool=pool).get("sess-1")
    phase = PhaseExecution(
        phase_id="verify",
        name="verify",
        status="failed",
        operations=[ApiToolOperation.model_validate(op, from_attributes=True) for op in operations],
    )
    return _map_phase_to_response(phase).operations


def _session_error_row(data: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": "session_error", "time": WHEN, "data": data}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_error_reaches_the_api_with_its_reason() -> None:
    """(a) The message the writer recorded is the message a client reads."""
    [operation] = await _operations_over_http(
        [
            _session_error_row(
                {"status": "failed", "error_message": "verify phase exited 1", "model": "haiku"}
            )
        ]
    )

    assert operation.error_message == "verify phase exited 1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_error_reports_success_as_false() -> None:
    """(b) `success: true` on the observation that records a failure is a lie."""
    [operation] = await _operations_over_http(
        [_session_error_row({"status": "failed", "error_message": "boom"})]
    )

    assert operation.success is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_failure_with_nothing_recorded_still_says_so() -> None:
    """(c) The read side never renders a blank reason, whatever it was given.

    The write side stopped producing blanks, but rows written before that are
    already stored, and a reader shown an empty field cannot tell "no reason"
    from "reason lost". Naming the gap is the honest answer.
    """
    [operation] = await _operations_over_http(
        [_session_error_row({"status": "failed", "error_message": "   "})]
    )

    assert operation.success is False
    assert operation.error_message is not None
    assert operation.error_message.strip()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_operation_id_is_well_formed_without_a_tool_id() -> None:
    """(d) A session-level row has no tool id and must not pretend it lost one."""
    [operation] = await _operations_over_http(
        [_session_error_row({"status": "failed", "error_message": "boom"})]
    )

    assert not operation.operation_id.startswith("-")
    assert "--" not in operation.operation_id
    assert operation.operation_id == f"session_error-{WHEN.isoformat()}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_row_stored_before_this_change_still_reads_back() -> None:
    """(e) Old rows carry no error_message key at all. Nothing may break.

    No stored schema changed, so this is the shape already sitting in
    Timescale: it must deserialize, and it must arrive describing itself
    rather than raising or rendering blank.
    """
    [operation] = await _operations_over_http(
        [_session_error_row({"status": "failed", "model": "haiku"})]
    )

    from syn_adapters.projections.session_tools_verdict import NO_REASON_RECORDED

    assert operation.success is False
    assert operation.error_message == NO_REASON_RECORDED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_in_flight_tool_is_not_reported_as_failed() -> None:
    """The verdict rule must not repaint everything that has no verdict.

    A started tool has no outcome yet. It keeps the pre-existing display
    default of True at this boundary - the dashboard reads `success` as a
    strict boolean and would paint every running operation red - and carries
    no error_message, because nothing has gone wrong.
    """
    [operation] = await _operations_over_http(
        [
            {
                "event_type": "tool_execution_started",
                "time": WHEN,
                "data": {"tool_name": "Bash", "tool_use_id": "toolu_1"},
            }
        ]
    )

    assert operation.success is True
    assert operation.error_message is None
    assert operation.operation_id == f"tool_execution_started-toolu_1-{WHEN.isoformat()}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_failed_tool_execution_carries_its_error_too() -> None:
    """The contract is keyed on the observation type, not on session_error.

    Fixing only the row named in the issue would have left the identical
    defect in every sibling type that also records a failure.
    """
    [operation] = await _operations_over_http(
        [
            {
                "event_type": "tool_execution_failed",
                "time": WHEN,
                "data": {"tool_name": "Bash", "tool_use_id": "toolu_1", "error": "exit status 2"},
            }
        ]
    )

    assert operation.success is False
    assert operation.error_message == "exit status 2"
