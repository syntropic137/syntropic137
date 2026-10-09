"""`POST /execute`'s two answers from the admission gate, as HTTP (#1387).

The gate decides; this only translates a refusal into the status a caller can
act on: 409 while maintenance is on, 507 while the workspace volume is full
(#1560). Split from `commands.py`, which holds the route that uses both.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts._shared import AdmissionTicket


async def refuse_while_paused() -> None:
    """Translate a paused admission gate into 409 (#1387).

    409 rather than 503: the request is well-formed and the service is up, the
    system state simply forbids it right now. A caller can tell that apart from
    a failure and retry after the deploy, which is the whole point of the gate
    having an answer at all.

    The cheap half of the check. It runs before validation so a caller during a
    deploy is told the gate is shut rather than told its workflow is missing,
    and so a paused system pays for no preflight. It decides nothing:
    :func:`admit_or_409` is what actually admits.
    """
    from syn_api._wiring_admission import get_admission_gate
    from syn_domain.contexts._shared import InsufficientDiskSpaceError, MaintenancePausedError

    try:
        await get_admission_gate().refuse_early()
    except MaintenancePausedError as exc:
        raise HTTPException(status_code=409, detail=exc.mode.refusal_detail) from None
    except InsufficientDiskSpaceError as exc:
        # #1560: 507 Insufficient Storage, before anything was written.
        raise HTTPException(status_code=507, detail=str(exc)) from None


@asynccontextmanager
async def admit_or_409() -> AsyncIterator[AdmissionTicket]:
    """Hold the gate open across the decisive step, or answer 409 (#1387).

    The decisive step for this route is ``background_tasks.add_task``: after it
    the response says 200 and the execution WILL run, whatever the flag says a
    moment later. So that one line goes inside here, and validation stays
    outside - a repo preflight held inside the gate would stall the operator's
    ``PUT /maintenance`` behind a network round trip.
    """
    from syn_api._wiring_admission import get_admission_gate
    from syn_domain.contexts._shared import InsufficientDiskSpaceError, MaintenancePausedError

    try:
        async with get_admission_gate().admitting() as ticket:
            yield ticket
    except MaintenancePausedError as exc:
        raise HTTPException(status_code=409, detail=exc.mode.refusal_detail) from None
    except InsufficientDiskSpaceError as exc:
        # #1560: 507 Insufficient Storage, before anything was written.
        raise HTTPException(status_code=507, detail=str(exc)) from None
