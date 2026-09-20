"""Maintenance mode: the operator's control over execution admission (#1387).

A deploy recreates the API container and kills whatever is running, so the
deploy script drains first. Draining alone only observes; this is what makes it
a gate. The sequence is: set here -> wait for the read path to reach the head ->
wait for terminal-only status counts -> swap -> clear here.

The state is durable (ADR-060), so the container that comes up on the far side
of the swap reads what was set before it and stays closed until told otherwise.
"""

from __future__ import annotations

from fastapi import APIRouter

from syn_api._wiring import get_admission_gate
from syn_api.types import MaintenanceModeResponse, SetMaintenanceModeRequest

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("", response_model=MaintenanceModeResponse)
async def get_maintenance_mode() -> MaintenanceModeResponse:
    """Report whether new executions are being admitted.

    Read through to the durable store, never from process memory, so this
    answers for the system rather than for this container.
    """
    mode = await get_admission_gate().current()
    return MaintenanceModeResponse(
        active=mode.active,
        reason=mode.reason,
        since=mode.since,
        actor=mode.actor,
    )


@router.put("", response_model=MaintenanceModeResponse)
async def set_maintenance_mode(request: SetMaintenanceModeRequest) -> MaintenanceModeResponse:
    """Pause or resume execution admission.

    Returns only once the state is durably stored AND every admission already
    part-way through deciding has finished deciding. That ordering is the whole
    point: a caller holding this response knows not only that the flag is set
    but that nothing is still on its way through the old answer, so there is no
    window on the setting side either.

    Set through the gate rather than the port, because the port can only store
    the flag - it cannot hold the door while it does so.
    """
    mode = await get_admission_gate().set_mode(
        active=request.active,
        reason=request.reason,
        actor=request.actor,
    )
    return MaintenanceModeResponse(
        active=mode.active,
        reason=mode.reason,
        since=mode.since,
        actor=mode.actor,
    )
