"""Sizes this process's execution budget from host capacity at startup, and reports it (#1715).

The formula and why demand is measured rather than read off the workspace caps
live in `syn_domain.contexts._shared.host_capacity`. This module does the I/O
around it: read the host, read the measured per-run demand, apply the result
to the ONE `ExecutionBudget` every start path claims from. With the Run Queue
on, `ExecutionHost` registers that same budget's limit as its capacity, so the
sized number is enforced on both claim paths.

Sized once, at startup, before the claim loop joins: the Run Queue records a
host's capacity when it joins, and re-sizing a live host is follow-up work.

Nothing here is durable, on purpose: a restart re-reads the host and the
profiles, which is the only correct source after a restart anyway.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring_admission import get_execution_budget
from syn_domain.contexts._shared.host_capacity import (
    BindingTerm,
    CapacityReserves,
    ExecutionBudgetSizing,
    HostCapacity,
    HostCapacityPort,
    RunDemand,
    size_execution_budget,
)

if TYPE_CHECKING:
    from syn_shared.settings.execution import ExecutionSettings

logger = logging.getLogger(__name__)

MIB = 2**20
GIB = 2**30

#: The measured demand over a window, None when too few phases were measured.
DemandReader = Callable[[timedelta], Awaitable[RunDemand | None]]


class ExecutionBudgetHealth(BaseModel):
    """The execution budget this process enforces, and what it is doing right now (#1715)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    budget: int = Field(description="Most executions this process runs at once.")
    binding_term: BindingTerm = Field(
        description="Which term set the budget: 'cpu', 'memory' or 'disk' when the host is "
        "the limit; 'operator_max' when SYN_EXECUTION_MAX_CONCURRENT is; "
        "'operator_max_no_profile' when too few phases have been measured to size from; "
        "'operator_max_profiles_unreadable' or 'operator_max_host_unreadable' when a read "
        "failed and the budget fell back to SYN_EXECUTION_MAX_CONCURRENT.",
    )
    admitted: int = Field(description="Starts accepted into the budget since this process began.")
    running: int = Field(description="Starts holding a slot now.")
    queued: int = Field(description="Starts waiting for a slot now.")
    cpu_pressure_avg60: float | None = Field(
        default=None,
        description="Percent of the last 60s some task on this host waited for CPU (PSI "
        "'some avg60'). Null where the kernel does not report it.",
    )


_sizing: ExecutionBudgetSizing | None = None
_host: HostCapacityPort | None = None


async def apply_host_sized_budget(
    host: HostCapacityPort,
    demand: DemandReader | None,
    settings: ExecutionSettings,
) -> ExecutionBudgetSizing:
    """Size the budget from ``host`` and ``demand`` and enforce it on every claim.

    ``demand`` is None where there is no profile store to read (test and
    offline), which sizes like a store with no profiles yet. A failed read
    falls back to the operator maximum and names the failure in the binding
    term: an unknown demand is not a small one.
    """
    global _sizing, _host
    _host = host
    operator_max = settings.max_concurrent
    try:
        capacity = host.read()
    except OSError:
        logger.warning("Could not read host capacity; execution budget is the operator maximum")
        sizing = ExecutionBudgetSizing(operator_max, BindingTerm.OPERATOR_MAX_HOST_UNREADABLE)
    else:
        measured, no_demand = await _read_demand(demand, settings)
        sizing = size_execution_budget(
            capacity, measured, _reserves(settings), operator_max, no_demand=no_demand
        )
    get_execution_budget().resize(sizing.budget)
    _sizing = sizing
    logger.info(
        "Execution budget %d, bound by %s (operator max %d)",
        sizing.budget,
        sizing.binding_term.value,
        operator_max,
    )
    return sizing


def describe_execution_budget() -> ExecutionBudgetHealth | None:
    """The budget block for /health; None before startup sized it. Never raises on the host."""
    if _sizing is None:
        return None
    budget = get_execution_budget()
    return ExecutionBudgetHealth(
        budget=budget.limit,
        binding_term=_sizing.binding_term,
        admitted=budget.admitted,
        running=budget.running,
        queued=budget.waiting,
        cpu_pressure_avg60=_cpu_pressure(),
    )


async def _read_demand(
    demand: DemandReader | None, settings: ExecutionSettings
) -> tuple[RunDemand | None, BindingTerm]:
    """The demand, and the binding term to report if there is none."""
    if demand is None:
        return None, BindingTerm.OPERATOR_MAX_NO_PROFILE
    try:
        measured = await demand(timedelta(days=settings.profile_window_days))
    except Exception:
        # Any failure of the profile store: the budget must still be set, and
        # the binding term carries the fact that it was not sized.
        logger.warning("Could not read phase profiles; execution budget is the operator maximum")
        return None, BindingTerm.OPERATOR_MAX_PROFILES_UNREADABLE
    return measured, BindingTerm.OPERATOR_MAX_NO_PROFILE


def _reserves(settings: ExecutionSettings) -> CapacityReserves:
    return CapacityReserves(
        platform_reserve_cores=settings.platform_reserve_cores,
        target_utilisation=settings.target_utilisation,
        memory_reserve_bytes=settings.memory_reserve_mb * MIB,
        disk_floor_bytes=int(settings.disk_floor_gib * GIB),
    )


def _cpu_pressure() -> float | None:
    if _host is None:
        return None
    try:
        capacity: HostCapacity = _host.read()
    except OSError:
        return None
    return capacity.cpu_pressure_avg60
