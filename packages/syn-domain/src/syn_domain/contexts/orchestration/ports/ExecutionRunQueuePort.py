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

from datetime import timedelta
from enum import IntEnum, StrEnum
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


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


class PoolDefinitionConflict(RuntimeError):
    """An executor declared a different definition for an Executor Pool that live members hold (D13)."""


_SLUG = r"^[a-z][a-z0-9-]{0,62}$"
PoolId = Annotated[str, StringConstraints(pattern=_SLUG)]
"""An Executor Pool's name. Operator data, so a validated slug, never an enum."""
ProviderId = Annotated[str, StringConstraints(pattern=_SLUG)]
"""What runs a pool's workspaces: ``docker`` today."""
RegionId = Annotated[str, StringConstraints(pattern=_SLUG)]
ReapScope = Annotated[str, StringConstraints(min_length=1, max_length=256)]
"""What one reaper can reach: a Docker engine ID, a provider account (D5, D13).

Derived from the backend, never configured. Opaque: compared for equality only.
"""


class Capability(StrEnum):
    """A feature of a pool's hosts that platform code must understand to use (D13)."""

    NESTED_DOCKER = "nested_docker"


class RunWorkload(StrEnum):
    """What a run needs its workspace to hold, as the claim reads it (#1917, decision 5).

    Recorded on the run row at reserve. Every run is ``AGENT`` until a start
    names a Scripted Agent profile (issue H).
    """

    AGENT = "agent"
    """A real agent: it needs the host's credentials."""
    SCRIPTED = "scripted"
    """A Scripted Agent: it needs no credential, so a NoCredentials pool may run it."""


class IsolationLevel(IntEnum):
    """How strongly a pool isolates one workspace from another; compared as a minimum (D13).

    Spaced so a level between the two (gVisor) needs no renumbering.
    """

    CONTAINER = 10
    """A shared kernel: runc."""
    MICROVM = 30
    """A kernel of its own: Kata, Firecracker, E2B."""


class ExecutorPool(BaseModel):
    """A named group of executors sharing a priority and what they can run (D13).

    One ``executor_pools`` row. Its capacity is the sum of its members'
    budgets: reported, never claimed against (D3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    pool_id: PoolId
    priority: int = Field(ge=0, le=32767)
    """0 is tried first."""
    provider: ProviderId
    region: RegionId | None = None
    isolation: IsolationLevel = IsolationLevel.CONTAINER
    capabilities: frozenset[Capability] = frozenset()
    overflow_delay: timedelta = Field(default=timedelta(seconds=60), ge=timedelta(0))
    """How long this pool's executors wait on a full higher-priority pool before overflowing."""
    supplies_credentials: bool = True
    """Whether the backend's Workspace Credential Policy supplies host credentials.

    False for a NoCredentials backend (E2B): its executors claim only
    ``SCRIPTED`` runs, and never hold an ``AGENT`` run back from a lower pool
    (#1917). Taken from the backend kit, never a setting.
    """

    @field_validator("overflow_delay")
    @classmethod
    def _whole_seconds(cls, value: timedelta) -> timedelta:
        # Stored as integer seconds: a fraction would never compare equal on re-register.
        if value.microseconds:
            raise ValueError("overflow_delay must be whole seconds")
        return value


DEFAULT_EXECUTOR_POOL = ExecutorPool(pool_id="default", priority=0, provider="docker")
"""The pool every executor joins unless it declares another; the schema seeds this row."""


class ExecutorHost(BaseModel):
    """One registered Executor process. A ``host_id`` is never reused (D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    host_id: str = Field(min_length=1, max_length=128)
    container_id: str = Field(min_length=1)
    generation: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    """The ``ORCHESTRATION_EVENT_EPOCH`` this host reads (D9)."""
    reap_scope: ReapScope
    """What this host's reaper can reach, from the reaper and never configured (D5, D13).

    A Docker engine ID today. This host fences and takes over only runs claimed
    in the same scope, so it never reports a reap of containers it cannot see.
    """
    pool: ExecutorPool = DEFAULT_EXECUTOR_POOL
    """The Executor Pool this host joins on ``register`` (D13)."""


class ClaimedRun(BaseModel):
    """A run an Executor holds; ``token`` is the fence every later write compares."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    execution_id: str
    executor_id: str
    token: int = Field(ge=1)
    is_resume: bool
    pool_id: PoolId
    """The Executor Pool the run was placed in (D13)."""
    overflowed: bool = False
    """A live higher-priority executor could have taken the run, and it spilled past (D13)."""


class FencedRun(BaseModel):
    """A run whose Lease expired, now owned by one reconciler (D5).

    ``executor_id`` is the dead host whose containers the reconciler reaps.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    execution_id: str
    executor_id: str
    reconciler: str
    token: int = Field(ge=1)
    reaped: bool = False
    """The row is ``reaped``: the dead host's containers are already gone."""


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

        First deletes any other host's row in the same ``container_id``: the
        restart is the proof that process stopped, so it has **left** (D5).
        Idempotent for the same host. Records ``host.reap_scope`` on the
        budget, and on any scope-less budget row in the same container (D13).
        ``capacity`` is seeded from
        ``SYN_EXECUTION_MAX_CONCURRENT`` by the caller (D12).

        Joins ``host.pool`` (D13): defines it if new. A declaration that differs
        from the stored definition overwrites it only when every other member
        is draining or no longer live; otherwise raises
        ``PoolDefinitionConflict`` and writes nothing.
        """
        ...

    async def deregister(self, host_id: str) -> None:
        """Delete the host's ``executor_hosts`` row: the host has **left** (D5)."""
        ...

    async def heartbeat(self, host_id: str) -> bool:
        """Write the host's ``heartbeat_at`` (D4); return whether it is draining (D10)."""
        ...

    async def is_draining(self, host_id: str) -> bool: ...

    async def others_live(self, host_id: str) -> bool:
        """Whether any executor other than ``host_id`` has a live heartbeat (D6)."""
        ...

    async def reserve(
        self,
        execution_id: str,
        writer_epoch: int,
        *,
        is_resume: bool,
        workload: RunWorkload = RunWorkload.AGENT,
    ) -> bool:
        """Insert an ``opening`` row. False when the execution already has one."""
        ...

    async def mark_admitted(self, execution_id: str) -> None:
        """``opening``/``abandoned`` -> ``admitted``; any other state is left alone."""
        ...

    async def claim(self, host_id: str) -> ClaimedRun | None:
        """Take the oldest run this host may take now, within its own capacity (D3, D13).

        One transaction. Stamps the host's Claim Check whenever it is live and
        not draining, with or without room. A run is taken only when the host's
        pool can run its workload and no live, non-draining executor in a
        higher-priority pool that could take it is claiming with room or has
        been full for less than this pool's Overflow Delay. Otherwise the run
        stays ``admitted`` (queued); it is never claimed and deferred.
        """
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

    async def fence_expired(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        """At most ``limit`` expired ``claimed`` runs this host can read and reap -> ``fencing``.

        Only runs whose claimer has this host's ``reap_scope``; a claimer with no
        scope, or another, is never fenced here and stays charged (D5, D13).

        Oldest ``leased_until`` first, owned by ``reconciler``. Two fencers never
        take the same row; the rest stay ``claimed`` for a later turn or another
        live host (D5).
        """
        ...

    async def take_over(self, reconciler: str, *, limit: int) -> list[FencedRun]:
        """At most ``limit`` ``fencing``/``reaped`` rows whose reconciler has **left**.

        Each is taken under a new token, oldest ``leased_until`` first. Leaving
        means its ``executor_hosts`` row is gone: a stale heartbeat alone is not
        leaving, so a stalled reconciler is never taken over while registered.
        Only rows whose claimer has this host's ``reap_scope`` (D5, D13).
        """
        ...

    async def reconciling(self, reconciler: str) -> list[FencedRun]:
        """Every ``fencing``/``reaped`` row ``reconciler`` owns, read from the row (D5).

        Read-only: it acquires nothing. Acquisition is ``fence_expired`` and
        ``take_over``, each bounded by the caller.
        """
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
