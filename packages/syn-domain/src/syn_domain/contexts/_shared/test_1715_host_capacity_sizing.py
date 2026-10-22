"""The execution budget formula, term by term (#1715)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from syn_domain.contexts._shared.host_capacity import (
    BindingTerm,
    CapacityReserves,
    HostCapacity,
    RunDemand,
    size_execution_budget,
)
from syn_domain.contexts.orchestration.slices.phase_profiles.query_service import (
    _resource_profiles,
    run_demand_from,
)

pytestmark = pytest.mark.unit

GIB = 2**30
HOST = HostCapacity(cpu_cores=34.0, memory_bytes=132 * GIB, disk_free_bytes=1010 * GIB)
RESERVES = CapacityReserves(
    platform_reserve_cores=2.0,
    target_utilisation=0.5,
    memory_reserve_bytes=4 * GIB,
    disk_floor_bytes=10 * GIB,
)


def _demand(cpu: float = 0.1, memory: float = GIB, disk: float = GIB) -> RunDemand:
    return RunDemand(cpu_cores_p50=cpu, memory_bytes_p95=memory, disk_bytes_p95=disk)


@pytest.mark.parametrize(
    ("demand", "budget", "term"),
    [
        # (34 - 2) x 0.5 / 1.6 = 10
        (_demand(cpu=1.6), 10, BindingTerm.CPU),
        # (132 - 4) / 9 = 14.2
        (_demand(memory=9 * GIB), 14, BindingTerm.MEMORY),
        # (1010 - 10) / 80 = 12.5
        (_demand(disk=80 * GIB), 12, BindingTerm.DISK),
        # every host term above 50
        (_demand(), 50, BindingTerm.OPERATOR_MAX),
    ],
)
def test_the_smallest_term_sets_the_budget_and_is_named(
    demand: RunDemand, budget: int, term: BindingTerm
) -> None:
    sizing = size_execution_budget(HOST, demand, RESERVES, operator_max=50)

    assert (sizing.budget, sizing.binding_term) == (budget, term)


def test_no_demand_is_the_operator_max() -> None:
    sizing = size_execution_budget(HOST, None, RESERVES, operator_max=13)

    assert (sizing.budget, sizing.binding_term) == (13, BindingTerm.OPERATOR_MAX_NO_PROFILE)


def _fits(capacity: HostCapacity, demand: RunDemand) -> list[float]:
    """Runs each measured resource holds after its reserve, computed independently."""
    return [
        (capacity.cpu_cores - RESERVES.platform_reserve_cores)
        * RESERVES.target_utilisation
        / demand.cpu_cores_p50,
        (capacity.memory_bytes - RESERVES.memory_reserve_bytes) / demand.memory_bytes_p95,
        (capacity.disk_free_bytes - RESERVES.disk_floor_bytes) / demand.disk_bytes_p95,
    ]


@pytest.mark.parametrize(
    ("capacity", "budget", "term"),
    [
        # every core is the platform's: (2 - 2) x 0.5 / 0.1 = 0
        (
            HostCapacity(cpu_cores=2.0, memory_bytes=132 * GIB, disk_free_bytes=1010 * GIB),
            0,
            BindingTerm.CPU,
        ),
        # less than one run's memory after the reserve: (4.5 - 4) / 1 = 0.5
        (
            HostCapacity(cpu_cores=34.0, memory_bytes=int(4.5 * GIB), disk_free_bytes=1010 * GIB),
            0,
            BindingTerm.MEMORY,
        ),
        # disk below its floor
        (
            HostCapacity(cpu_cores=34.0, memory_bytes=132 * GIB, disk_free_bytes=5 * GIB),
            0,
            BindingTerm.DISK,
        ),
        # a normal host still grants runs
        (HOST, 50, BindingTerm.OPERATOR_MAX),
    ],
)
def test_the_budget_never_exceeds_any_measured_term(
    capacity: HostCapacity, budget: int, term: BindingTerm
) -> None:
    """A host that fits no run gets a budget of 0, not 1: admitting one breaks the bound."""
    demand = _demand()

    sizing = size_execution_budget(capacity, demand, RESERVES, operator_max=50)

    assert (sizing.budget, sizing.binding_term) == (budget, term)
    assert all(sizing.budget <= max(0.0, fits) for fits in _fits(capacity, demand))


@dataclass(frozen=True)
class _Row:
    """Stands in for an asyncpg.Record: subscriptable by column name."""

    execution_id: str
    phase_id: str
    usages: list[str]

    def __getitem__(self, column: str) -> str | list[str]:
        return getattr(self, column)


def _rows(count: int) -> list[_Row]:
    return [
        _Row(
            execution_id=f"exec-{i}",
            phase_id="*",
            usages=[
                json.dumps(
                    {
                        "cpu_usage_seconds": 30.0 * (i + 1),
                        "workspace_lifetime_seconds": 100.0,
                        "memory_peak_bytes": (i + 1) * GIB,
                        "disk_bytes_at_teardown": (i + 1) * 2 * GIB,
                    }
                )
            ],
        )
        for i in range(count)
    ]


def test_pooled_profiles_give_the_median_cpu_and_p95_memory_and_disk() -> None:
    demand = run_demand_from(_resource_profiles(_rows(11)))

    assert demand is not None
    # cpu rates 0.3 .. 3.3, median 1.8; memory 1..11 GiB, p95 10.5 GiB
    assert demand.cpu_cores_p50 == pytest.approx(1.8)
    assert demand.memory_bytes_p95 == pytest.approx(10.5 * GIB)
    assert demand.disk_bytes_p95 == pytest.approx(21 * GIB)


def test_too_few_measured_phases_is_no_demand() -> None:
    assert run_demand_from(_resource_profiles(_rows(9))) is None
