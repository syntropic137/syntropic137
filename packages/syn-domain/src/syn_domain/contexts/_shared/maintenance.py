"""Maintenance mode: the admission gate for new workflow executions (#1387).

A deploy recreates the API container, which kills whatever is in flight, so the
deploy script drains first. That drain only *observes* - it polls status counts
until they are terminal and then swaps. Nothing stops work arriving in the gap:
``POST /workflows/{id}/execute`` returns before its background task has
persisted anything, and GitHub triggers dispatch on their own schedule with no
operator involved at all.

Maintenance mode is what closes it. While it is active every admission path
refuses; executions already running are untouched, because this gates admission,
not execution.

Two properties make it a gate rather than a second observation, and both belong
to the port, not to any one caller:

* ``set_mode`` persists before it returns, so nothing can be admitted after the
  operator's call comes back.
* ``current`` reads through to the durable store every time and caches nothing,
  so an API container that starts in the middle of a deploy comes back still
  refusing instead of silently re-opening admission (ADR-060).

Lives in the shared kernel because both contexts that admit executions need it:
``orchestration`` (the HTTP path) and ``github`` (trigger dispatch). One
declaration, so the two cannot drift apart on what "paused" means.
"""

from __future__ import annotations

# NOT in a TYPE_CHECKING block, despite TC003: `MaintenanceMode` is a
# Pydantic model and Pydantic resolves `since: datetime | None` against
# this module's real namespace at class-build time.
from datetime import datetime  # noqa: TC003
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class MaintenanceMode(BaseModel):
    """Whether new workflow executions may be admitted, and why not.

    The default is the open state, so a store that has never been written
    reads as "admission open" without anyone having to say so.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active: bool = False
    reason: str = ""
    since: datetime | None = None
    actor: str = ""

    @property
    def refusal_detail(self) -> str:
        """The one sentence every admission path gives back when it refuses.

        Built here rather than at each call site so the 409 body, the trigger
        history record and the log line cannot describe the same refusal
        differently.
        """
        reason = self.reason.strip() or "deployment in progress"
        since = f" since {self.since.isoformat()}" if self.since is not None else ""
        return (
            f"Execution admission is paused{since}: {reason}. "
            "Running executions are unaffected; retry once maintenance mode clears."
        )


class MaintenancePausedError(Exception):
    """Raised instead of admitting an execution while maintenance mode is active.

    Carries the mode so the entry point that catches it can translate the
    refusal into its own protocol's answer - a 409 over HTTP, a ``paused``
    dispatch record for a trigger - rather than reporting a generic failure.
    """

    def __init__(self, mode: MaintenanceMode) -> None:
        super().__init__(mode.refusal_detail)
        self.mode = mode


@runtime_checkable
class MaintenancePort(Protocol):
    """Durable store for maintenance mode.

    Implementations MUST write through to durable storage before returning from
    ``set_mode`` and MUST read through to it on every ``current`` call. An
    implementation that caches, or that keeps the state in process memory,
    re-opens admission on restart and is the failure ADR-060 exists to forbid.
    """

    async def current(self) -> MaintenanceMode:
        """Return the state as durably stored right now."""
        ...

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        """Persist the state and return what was stored. Durable before return."""
        ...


async def refuse_if_paused(port: MaintenancePort) -> None:
    """Raise :class:`MaintenancePausedError` if admission is closed.

    The single predicate. Every admission path calls this and translates the
    exception; none of them re-decides what "paused" means.
    """
    mode = await port.current()
    if mode.active:
        raise MaintenancePausedError(mode)
