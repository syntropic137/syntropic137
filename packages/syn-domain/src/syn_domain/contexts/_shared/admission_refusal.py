"""The family every admission refusal belongs to (#1560).

Admission can be refused for more than one reason - a deploy holds the door
(#1387), the workspace volume is below its free-space floor (#1560) - and every
reason so far is temporary: it clears without anyone touching the refused work.
A process manager that parks work behind the gate must therefore hold the work,
not fail it, whatever the reason was.

Catching each reason by name is how #1560 first shipped a dropped trigger: the
dispatcher knew `MaintenancePausedError` and sent the disk refusal down its
generic failure path. Catch this base instead, and a new reason is held the day
it is added. Only an entry point that answers differently per reason (the HTTP
routes: 409 for a deploy, 507 for a full disk) should name the subclasses.
"""

from __future__ import annotations

from typing import ClassVar


class AdmissionRefusedError(Exception):
    """Admission refused for a reason that clears on its own; retry later.

    ``hold_reason`` is the machine-readable word a held record carries, so the
    trigger history says WHY a dispatch is waiting. ``str(exc)`` is the
    operator-facing sentence.
    """

    hold_reason: ClassVar[str]
