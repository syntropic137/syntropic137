"""How many executions this host can run, from what it has and what a run uses (#1715).

The execution budget used to be a hand-set constant (4). It is now the
smallest of four terms, and the one that wins is reported as the binding term:

    budget = min(operator_max,
                 (cores - platform_reserve) x target_utilisation / cpu_p50,
                 (memory - memory_reserve) / memory_p95,
                 (disk_free - disk_floor) / disk_p95)

DEMAND IS MEASURED, NEVER THE CAP. The per-run figures come from the phase
resource profiles (#1716): what workspaces actually used. The workspace
container limits (SYN_WORKSPACE_CPU_LIMIT, SYN_WORKSPACE_MEMORY_LIMIT_MB) are
ceilings a run may never reach, and sizing from them would keep the budget at
whatever an operator once guessed. Nothing in this module reads them.

NO PROFILE, NO GUESS. Without enough measured phases there is no demand to
divide by, so the budget is the operator maximum and the binding term says
why. A computed budget is never padded out with an estimate.

The host is read through `HostCapacityPort`, so tests size a budget against a
host that does not exist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class HostCapacity:
    """What this host has, at the moment it was read."""

    cpu_cores: float
    memory_bytes: int
    disk_free_bytes: int
    cpu_pressure_avg60: float | None = None
    """Percent of the last 60s some task waited for CPU (PSI); None where unsupported."""


class HostCapacityPort(Protocol):
    """Reads the host's capacity. Raises ``OSError`` if the host cannot be read."""

    def read(self) -> HostCapacity: ...


@dataclass(frozen=True)
class RunDemand:
    """What one running execution uses, measured from its phases' workspaces."""

    cpu_cores_p50: float
    """Median CPU seconds per wall second: cores held."""
    memory_bytes_p95: float
    disk_bytes_p95: float


@dataclass(frozen=True)
class CapacityReserves:
    """What the host keeps back from executions, and how full it may run."""

    platform_reserve_cores: float
    target_utilisation: float
    memory_reserve_bytes: int
    disk_floor_bytes: int


class BindingTerm(StrEnum):
    """Which term of the formula set the budget."""

    OPERATOR_MAX = "operator_max"
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    OPERATOR_MAX_NO_PROFILE = "operator_max_no_profile"
    """No measured demand yet: too few profiled phases to divide by."""
    OPERATOR_MAX_PROFILES_UNREADABLE = "operator_max_profiles_unreadable"
    """The profiles could not be read, so the demand is unknown, not small."""
    OPERATOR_MAX_HOST_UNREADABLE = "operator_max_host_unreadable"
    """The host's capacity could not be read."""


@dataclass(frozen=True)
class ExecutionBudgetSizing:
    """A sized budget and the term that bound it."""

    budget: int
    binding_term: BindingTerm


def size_execution_budget(
    capacity: HostCapacity,
    demand: RunDemand | None,
    reserves: CapacityReserves,
    operator_max: int,
    *,
    no_demand: BindingTerm = BindingTerm.OPERATOR_MAX_NO_PROFILE,
) -> ExecutionBudgetSizing:
    """The budget for ``capacity`` running runs that use ``demand``.

    It may be 0. A host whose reserves leave less than one measured run's
    worth of CPU, memory or disk fits no run, and admitting one anyway would
    break the bound this formula exists to keep. Starts queue instead, and
    the binding term names the resource that is short.
    """
    if demand is None:
        return ExecutionBudgetSizing(budget=operator_max, binding_term=no_demand)
    terms = [
        (float(operator_max), BindingTerm.OPERATOR_MAX),
        (
            _per_run(
                (capacity.cpu_cores - reserves.platform_reserve_cores)
                * reserves.target_utilisation,
                demand.cpu_cores_p50,
            ),
            BindingTerm.CPU,
        ),
        (
            _per_run(
                capacity.memory_bytes - reserves.memory_reserve_bytes, demand.memory_bytes_p95
            ),
            BindingTerm.MEMORY,
        ),
        (
            _per_run(capacity.disk_free_bytes - reserves.disk_floor_bytes, demand.disk_bytes_p95),
            BindingTerm.DISK,
        ),
    ]
    # min() keeps the first of equal terms, so a tie names the operator first.
    runs, term = min(terms, key=lambda t: t[0])
    return ExecutionBudgetSizing(budget=math.floor(runs), binding_term=term)


def _per_run(available: float, per_run: float) -> float:
    """Runs that fit in ``available``; unlimited when a run uses none of it."""
    if per_run <= 0:
        return math.inf
    return max(0.0, available) / per_run
