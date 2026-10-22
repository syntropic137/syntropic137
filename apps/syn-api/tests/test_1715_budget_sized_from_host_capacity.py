"""The execution budget is sized from host capacity and ENFORCED on every claim path (#1715).

Each test drives the consumer, not the arithmetic: the claim that queues, the
capacity the Run Queue host registers, the /health payload. A budget computed
correctly and dropped one hop later passes every test of the formula alone.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

import syn_api._wiring_admission as admission
from syn_api.execution_budget import ExecutionBudget, StartPath
from syn_api.services import execution_capacity, lifecycle
from syn_api.types import Ok
from syn_domain.contexts._shared.host_capacity import (
    BindingTerm,
    HostCapacity,
    RunDemand,
)
from syn_shared.env_constants import ENV_SYN_EXECUTION_MAX_CONCURRENT
from syn_shared.settings.config import AppEnvironment, Settings
from syn_shared.settings.execution import ExecutionSettings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import timedelta

pytestmark = pytest.mark.unit

GIB = 2**30


@dataclass
class HostDouble:
    """A host that does not exist: `HostCapacityPort` for tests."""

    capacity: HostCapacity

    def read(self) -> HostCapacity:
        return self.capacity


class UnreadableHost:
    def read(self) -> HostCapacity:
        raise OSError("host not readable")


#: 16 cores, 64 GiB, 500 GiB free, and a PSI reading no default produces.
BIG_HOST = HostCapacity(
    cpu_cores=16.0, memory_bytes=64 * GIB, disk_free_bytes=500 * GIB, cpu_pressure_avg60=7.25
)
#: What one run measured: memory binds at (64 - 4) / 30 = 2.
MEMORY_BOUND_DEMAND = RunDemand(cpu_cores_p50=0.5, memory_bytes_p95=30 * GIB, disk_bytes_p95=GIB)


@pytest.fixture(autouse=True)
def fresh_budget(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A budget at the operator max, as the process holds it before sizing."""
    monkeypatch.setattr(admission, "_execution_budget_singleton", ExecutionBudget(10))
    monkeypatch.setattr(execution_capacity, "_sizing", None)
    monkeypatch.setattr(execution_capacity, "_host", None)
    yield


def _execution(max_concurrent: int = 10) -> ExecutionSettings:
    return ExecutionSettings.model_validate({ENV_SYN_EXECUTION_MAX_CONCURRENT: max_concurrent})


def _demand(demand: RunDemand | None):
    async def read(_window: timedelta) -> RunDemand | None:
        return demand

    return read


async def test_a_budget_of_two_queues_the_third_run_on_the_real_claim() -> None:
    """TRAP 2: the sized budget is the limit the claim path enforces, not a number on /health."""
    sizing = await execution_capacity.apply_host_sized_budget(
        HostDouble(BIG_HOST), _demand(MEMORY_BOUND_DEMAND), _execution()
    )
    assert (sizing.budget, sizing.binding_term) == (2, BindingTerm.MEMORY)

    budget = admission.get_execution_budget()
    claims = [budget.claim(f"exec-{i}", workflow_id="wf", path=StartPath.DIRECT) for i in range(3)]
    entered: list[str] = []
    release = asyncio.Event()

    async def run(claim) -> None:
        async with budget.held(claim):
            entered.append(claim.execution_id)
            await release.wait()

    tasks = [asyncio.create_task(run(c)) for c in claims]
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert entered == ["exec-0", "exec-1"]
    third = budget.position("exec-2")
    assert third is not None
    assert third.queued and third.position == 1 and third.limit == 2

    release.set()
    await asyncio.gather(*tasks)
    assert entered == ["exec-0", "exec-1", "exec-2"]


async def test_a_host_that_fits_no_run_queues_every_start_on_the_real_claim() -> None:
    """A budget of 0 is enforced as 0: the start queues rather than being let in."""
    all_reserved = HostCapacity(cpu_cores=2.0, memory_bytes=64 * GIB, disk_free_bytes=500 * GIB)
    sizing = await execution_capacity.apply_host_sized_budget(
        HostDouble(all_reserved), _demand(MEMORY_BOUND_DEMAND), _execution()
    )
    assert (sizing.budget, sizing.binding_term) == (0, BindingTerm.CPU)

    budget = admission.get_execution_budget()
    claim = budget.claim("exec-0", workflow_id="wf", path=StartPath.DIRECT)
    entered: list[str] = []

    async def run() -> None:
        async with budget.held(claim):
            entered.append(claim.execution_id)

    task = asyncio.create_task(run())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert entered == []
    position = budget.position("exec-0")
    assert position is not None and position.queued and position.limit == 0

    # Capacity that fits runs again grants the queued start.
    budget.resize(1)
    await task
    assert entered == ["exec-0"]


@pytest.mark.parametrize(
    ("cpu_limit", "memory_limit_mb"), [("2.0", "4096"), ("8.0", "16384"), ("0.5", "512")]
)
async def test_the_workspace_caps_do_not_change_the_budget(
    monkeypatch: pytest.MonkeyPatch, cpu_limit: str, memory_limit_mb: str
) -> None:
    """TRAP 1: demand is the measured p50/p95, never SYN_WORKSPACE_CPU/MEMORY limits.

    Driven through the startup composition with a non-test Settings, so the
    measured demand is actually read. From the caps the budget would be
    (64 - 4) GiB / 4096 MB = 15, then 3, then 120; from the measurement it is 2.
    """
    monkeypatch.setenv("SYN_WORKSPACE_CPU_LIMIT", cpu_limit)
    monkeypatch.setenv("SYN_WORKSPACE_MEMORY_LIMIT_MB", memory_limit_mb)
    monkeypatch.setenv("SYN_EXECUTION_MAX_CONCURRENT", "10")

    class Profiles:
        async def run_demand(self, _window: timedelta) -> RunDemand | None:
            return MEMORY_BOUND_DEMAND

    import syn_adapters.host_capacity as host_capacity
    import syn_api._wiring as wiring

    monkeypatch.setattr(host_capacity, "build_host_capacity", lambda: HostDouble(BIG_HOST))
    monkeypatch.setattr(wiring, "get_phase_profile_query", Profiles)
    settings = Settings(app_environment=AppEnvironment.DEVELOPMENT)
    assert settings.workspace.cpu_limit == float(cpu_limit)

    import syn_shared.settings as shared_settings

    monkeypatch.setattr(shared_settings, "get_settings", lambda: settings)
    await execution_capacity.size_execution_budget_at_startup()

    assert admission.get_execution_budget().limit == 2


async def test_health_reports_the_budget_and_its_binding_term() -> None:
    await execution_capacity.apply_host_sized_budget(
        HostDouble(BIG_HOST), _demand(MEMORY_BOUND_DEMAND), _execution()
    )
    budget = admission.get_execution_budget()
    for i in range(3):
        budget.claim(f"exec-{i}", workflow_id="wf", path=StartPath.TRIGGER)

    result = await lifecycle.health_check()
    assert isinstance(result, Ok)

    assert result.value.model_dump(mode="json")["execution_budget"] == {
        "budget": 2,
        "binding_term": "memory",
        "admitted": 3,
        "running": 2,
        "queued": 1,
        "cpu_pressure_avg60": 7.25,
    }


async def test_no_profile_data_is_the_operator_max_and_says_so() -> None:
    sizing = await execution_capacity.apply_host_sized_budget(
        HostDouble(BIG_HOST), _demand(None), _execution(max_concurrent=7)
    )

    assert (sizing.budget, sizing.binding_term) == (7, BindingTerm.OPERATOR_MAX_NO_PROFILE)
    assert admission.get_execution_budget().limit == 7


async def test_an_unreadable_profile_store_is_named_not_mistaken_for_no_data() -> None:
    async def broken(_window: timedelta) -> RunDemand | None:
        raise ConnectionError("timescale is down")

    sizing = await execution_capacity.apply_host_sized_budget(
        HostDouble(BIG_HOST), broken, _execution(max_concurrent=7)
    )

    assert (sizing.budget, sizing.binding_term) == (
        7,
        BindingTerm.OPERATOR_MAX_PROFILES_UNREADABLE,
    )


async def test_an_unreadable_host_is_named() -> None:
    sizing = await execution_capacity.apply_host_sized_budget(
        UnreadableHost(), _demand(MEMORY_BOUND_DEMAND), _execution(max_concurrent=7)
    )

    assert (sizing.budget, sizing.binding_term) == (7, BindingTerm.OPERATOR_MAX_HOST_UNREADABLE)
    assert admission.get_execution_budget().limit == 7


async def test_the_run_queue_host_registers_the_sized_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Correction A: with the Run Queue on, the claim loop's capacity is the sized budget."""
    from syn_api.services import execution_host_runner as runner

    await execution_capacity.apply_host_sized_budget(
        HostDouble(BIG_HOST), _demand(MEMORY_BOUND_DEMAND), _execution()
    )
    registered: list[int] = []

    class Host:
        def __init__(self, *_args: object, capacity: int, **_kwargs: object) -> None:
            registered.append(capacity)

        async def join(self) -> None:
            return None

        async def run_until_drained(self) -> None:
            return None

    async def queue() -> object:
        return object()

    async def nothing(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(runner, "ExecutionHost", Host)
    monkeypatch.setattr(runner, "get_execution_run_queue", queue)
    monkeypatch.setattr(runner, "get_execution_processor", nothing)
    monkeypatch.setattr(runner, "reap_unlabelled_if_alone", nothing)
    monkeypatch.setattr(
        runner.DockerDeadHostReaper,
        "for_local_engine",
        AsyncMock(return_value=runner.DockerDeadHostReaper("engine-1")),
    )
    monkeypatch.setattr(runner, "get_execution_event_stream", lambda: None, raising=False)
    monkeypatch.setattr(runner, "_host_task", None)
    try:
        await runner.start_execution_host()
    finally:
        task = runner._host_task
        if task is not None:
            await task
        monkeypatch.setattr(runner, "_executor", None)

    assert registered == [2]


async def test_startup_sizes_from_profiles_read_through_the_pool_the_event_store_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sizing runs after the event store opens its pool, through the real profile wiring.

    Sized before it, the real `get_phase_profile_query()` raises on a pool that
    is still None, and every fresh process falls back to the operator maximum.
    Only the store's connection and the SQL are doubled here.
    """
    import syn_adapters.host_capacity as host_capacity
    import syn_api._wiring as wiring
    import syn_shared.settings as shared_settings
    from syn_domain.contexts.orchestration import PhaseProfileQueryService

    opened = object()

    class EventStore:
        pool: object | None = None

        async def initialize(self) -> None:
            self.pool = opened

    store = EventStore()

    async def connected() -> None:
        return None

    async def measured(self: PhaseProfileQueryService, _window: timedelta) -> RunDemand | None:
        assert self._pool is opened
        return MEMORY_BOUND_DEMAND

    settings = Settings(app_environment=AppEnvironment.DEVELOPMENT)
    monkeypatch.setattr(shared_settings, "get_settings", lambda: settings)
    monkeypatch.setattr(wiring, "get_event_store_instance", lambda: store)
    monkeypatch.setattr(lifecycle, "get_event_store_instance", lambda: store)
    monkeypatch.setattr(lifecycle, "ensure_connected", connected)
    monkeypatch.setattr(lifecycle, "_validate_workspace_settings", lambda: Ok(None))
    monkeypatch.setattr(PhaseProfileQueryService, "run_demand", measured)
    monkeypatch.setattr(host_capacity, "build_host_capacity", lambda: HostDouble(BIG_HOST))

    assert isinstance(await lifecycle._init_critical_path(), Ok)

    health = await execution_capacity.describe_execution_budget()
    assert health is not None
    assert (health.budget, health.binding_term) == (2, BindingTerm.MEMORY)
    assert admission.get_execution_budget().limit == 2


async def test_health_counts_the_run_queue_when_starts_go_through_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the Run Queue on, starts never touch the in-process budget: /health reads the queue."""
    import syn_api._wiring as wiring
    from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
    from syn_domain.contexts.orchestration.ports import ExecutorHost

    await execution_capacity.apply_host_sized_budget(
        HostDouble(BIG_HOST), _demand(MEMORY_BOUND_DEMAND), _execution()
    )
    queue = InMemoryExecutionRunQueue()

    async def run_queue() -> InMemoryExecutionRunQueue:
        return queue

    monkeypatch.setattr(wiring, "get_execution_run_queue", run_queue)
    host = ExecutorHost(
        host_id="h", container_id="c", generation="g", epoch=1, reap_scope="engine-1"
    )
    await queue.register(host, admission.get_execution_budget().limit)
    await queue.heartbeat(host.host_id)
    for i in range(3):
        assert await queue.reserve(f"exec-{i}", 1, is_resume=False)
        await queue.mark_admitted(f"exec-{i}")
    claimed = [run for _ in range(3) if (run := await queue.claim("h")) is not None]
    assert len(claimed) == 2

    async def counts() -> tuple[int, int, int, int, str]:
        result = await lifecycle.health_check()
        assert isinstance(result, Ok)
        block = result.value.execution_budget
        assert block is not None
        return block.budget, block.admitted, block.running, block.queued, block.binding_term

    assert await counts() == (2, 3, 2, 1, "memory")

    await queue.close(claimed[0])
    third = await queue.claim("h")
    assert third is not None
    assert await counts() == (2, 3, 2, 0, "memory")

    for run in (claimed[1], third):
        await queue.close(run)
    assert await counts() == (2, 3, 0, 0, "memory")
