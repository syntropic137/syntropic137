"""Port for the Run Queue: where admitted Executions wait for an Executor (ADR-072).

Infrastructure state, never a projection (ADR-072 D2). Operations are named for
what callers do, not as a generic lease API. Every transition is a guarded
compare-and-set: a caller whose token was superseded gets ``RunLeaseLost`` and
changes nothing, so a slot is charged and released exactly once (D3).

Row states: ``opening -> admitted -> claimed -> done``; an expired Lease goes
``claimed -> fencing -> reaped -> interrupted`` (D5); ``defer`` returns a
claimed run to ``admitted`` (D7); ``opening`` is swept to ``admitted`` or the
provisional ``abandoned`` (D2).
"""

from __future__ import annotations

from datetime import timedelta  # noqa: TC003
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class RunLeaseLost(RuntimeError):
    """The run's lease token was superseded, or the run left the state the caller held."""


class StreamPresence(StrEnum):
    """What a read of an Execution's stream established. UNKNOWN is never ABSENT (D2)."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class ExecutionStreamProbe(Protocol):
    """Reads whether an Execution's stream exists, for the ``opening`` sweep."""

    async def presence(self, execution_id: str) -> StreamPresence: ...


class ExecutorHost(BaseModel):
    """One registered Executor process. A ``host_id`` is never reused (D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    host_id: str = Field(min_length=1, max_length=128)
    container_id: str = Field(min_length=1)
    generation: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    """The ``ORCHESTRATION_EVENT_EPOCH`` this host reads (D9)."""


class ClaimedRun(BaseModel):
    """A run an Executor holds; ``token`` is the fence every later write compares."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    execution_id: str
    executor_id: str
    token: int = Field(ge=1)
    is_resume: bool


class FencedRun(BaseModel):
    """A run whose Lease expired, now owned by one reconciler (D5).

    ``executor_id`` is the dead host whose containers the reconciler reaps.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    execution_id: str
    executor_id: str
    reconciler: str
    token: int = Field(ge=1)


class OpeningSweep(BaseModel):
    """What one ``sweep_opening`` turn resolved. Rows read as UNKNOWN appear in neither."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    admitted: tuple[str, ...] = ()
    abandoned: tuple[str, ...] = ()


class RunCounts(BaseModel):
    """Run rows in each state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    opening: int = 0
    admitted: int = 0
    claimed: int = 0
    fencing: int = 0
    reaped: int = 0
    abandoned: int = 0
    done: int = 0
    interrupted: int = 0


class ExecutionRunQueue(Protocol):
    """The Run Queue. Production is Postgres-only; there is no fallback (ADR-060)."""

    async def register(self, host: ExecutorHost, capacity: int) -> None:
        """Add the host's ``executor_hosts`` row and its own ``execution_budget`` row.

        Idempotent for the same host. ``capacity`` is seeded from
        ``SYN_EXECUTION_MAX_CONCURRENT`` by the caller (D12).
        """
        ...

    async def deregister(self, host_id: str) -> None:
        """Delete the host's ``executor_hosts`` row: the host has **left** (D5)."""
        ...

    async def heartbeat(self, host_id: str) -> bool:
        """Write the host's ``heartbeat_at`` (D4); return whether it is draining (D10)."""
        ...

    async def is_draining(self, host_id: str) -> bool: ...

    async def reserve(self, execution_id: str, writer_epoch: int, *, is_resume: bool) -> bool:
        """Insert an ``opening`` row. False when the execution already has one."""
        ...

    async def mark_admitted(self, execution_id: str) -> None:
        """``opening``/``abandoned`` -> ``admitted``; any other state is left alone."""
        ...

    async def claim(self, host_id: str) -> ClaimedRun | None:
        """Take the oldest claimable run within this host's own capacity, in one transaction (D3)."""
        ...

    async def renew(self, run: ClaimedRun) -> None:
        """Extend the Lease. Raises ``RunLeaseLost`` if expired, fenced or released."""
        ...

    async def defer(self, run: ClaimedRun, retry_after: timedelta, reason: str) -> None:
        """``claimed`` -> ``admitted`` with ``retry_at``; releases the slot (D3, D7)."""
        ...

    async def close(self, run: ClaimedRun) -> None:
        """``claimed`` -> ``done``; releases the slot (D3)."""
        ...

    async def fence_expired(self, reconciler: str) -> list[FencedRun]:
        """Every expired ``claimed`` run this host can read -> ``fencing``, owned by ``reconciler``."""
        ...

    async def mark_reaped(self, run: FencedRun) -> None:
        """``fencing`` -> ``reaped`` once the dead host's containers are gone (D5)."""
        ...

    async def close_interrupted(self, run: FencedRun) -> None:
        """``reaped`` -> ``interrupted``; releases the claimer's slot (D5 step 2)."""
        ...

    async def sweep_opening(
        self, older_than: timedelta, streams: ExecutionStreamProbe
    ) -> OpeningSweep:
        """Resolve stranded ``opening`` rows and re-read ``abandoned`` ones (D2)."""
        ...

    async def in_use(self) -> RunCounts: ...
