"""EXPERIMENT 1: can two appends at the same expected version both succeed?

The decision's guards 1 and 2 rest on this: "forked at most once" is enforced
by optimistic concurrency on the parent stream, and the deterministic fork id
by NoStream on the fork stream.

HAZARD, not a near miss: two writers that have LOADED THE SAME VERSION of one
stream and append CONCURRENTLY (asyncio.gather over a real network client),
each with an event the aggregate legitimately accepts. A sequential second
append would fail safe for the wrong reason (it would see the first write).

Run against:
  - MemoryEventStoreClient (what every unit test uses), and
  - GrpcEventStoreClient -> Rust eventstore-bin -> Postgres 16 (production
    shape, docker/docker-compose.syntropic137.yaml:74 BACKEND=postgres), when
    EXP_GRPC_ADDR is set.

Each race records whether the two append calls actually OVERLAPPED in time.
A race that never overlapped proves nothing; that is this experiment's
"assert the mutation applied".
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import Counter
from typing import Any

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
    InterruptExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)

pytestmark = pytest.mark.unit
N = int(os.environ.get("EXP_N", "200"))


class Timed:
    """Delegating client that timestamps append_events; optionally mutated."""

    def __init__(self, inner: Any, *, drop_expected_version: bool = False) -> None:  # noqa: ANN401
        self._inner = inner
        self.spans: list[tuple[float, float]] = []
        self.drop = drop_expected_version
        self.mutated_calls = 0

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self._inner, name)

    async def append_events(self, stream_name: str, events: Any, expected_version: Any = None) -> None:  # noqa: ANN401
        if self.drop:
            expected_version = None
            self.mutated_calls += 1
        t0 = time.perf_counter()
        try:
            await self._inner.append_events(stream_name=stream_name, events=events,
                                            expected_version=expected_version)
        finally:
            self.spans.append((t0, time.perf_counter()))


async def _client() -> tuple[str, Any]:
    addr = os.environ.get("EXP_GRPC_ADDR")
    if addr:
        from event_sourcing.client.grpc_client import GrpcEventStoreClient

        c = GrpcEventStoreClient(address=addr, tenant_id="exp")
        await c.connect()
        return "grpc+postgres", c
    return "memory", MemoryEventStoreClient()


def _started(eid: str, task: str) -> WorkflowExecutionAggregate:
    agg = WorkflowExecutionAggregate()
    agg._handle_command(StartExecutionCommand(execution_id=eid, workflow_id="wf", workflow_name="W",
                                              total_phases=1, inputs={"task": task}))
    return agg


def _overlapped(spans: list[tuple[float, float]]) -> bool:
    (a0, a1), (b0, b1) = spans[-2], spans[-1]
    return max(a0, b0) < min(a1, b1)


async def _race_existing_stream(timed: Timed) -> tuple[str, bool, int]:
    repo = EventStoreRepository(timed, WorkflowExecutionAggregate, "WorkflowExecution")
    eid = f"exec-{uuid.uuid4().hex[:12]}"
    await repo.save_new(_started(eid, "x"))
    a = await repo.load(eid)
    b = await repo.load(eid)
    assert a is not None and b is not None
    assert a.version == b.version == 1  # same expected version: precondition of the hazard
    a._handle_command(CancelExecutionCommand(execution_id=eid, phase_id="p1", reason="A"))
    b._handle_command(InterruptExecutionCommand(execution_id=eid, phase_id="p1", reason="B"))
    res = await asyncio.gather(repo.save(a), repo.save(b), return_exceptions=True)
    ok = sum(1 for r in res if r is None)
    errs = sorted(type(r).__name__ for r in res if r is not None)
    final = await repo.load(eid)
    assert final is not None
    return f"ok={ok} errs={errs}", _overlapped(timed.spans), final.version


async def _race_no_stream(timed: Timed) -> tuple[str, bool, int]:
    repo = EventStoreRepository(timed, WorkflowExecutionAggregate, "WorkflowExecution")
    eid = f"exec-{uuid.uuid4().hex[:12]}"
    res = await asyncio.gather(repo.save_new(_started(eid, "first")),
                               repo.save_new(_started(eid, "second")), return_exceptions=True)
    ok = sum(1 for r in res if r is None)
    errs = sorted(f"{type(r).__name__}" for r in res if r is not None)
    final = await repo.load(eid)
    return f"ok={ok} errs={errs}", _overlapped(timed.spans), (final.version if final else 0)


@pytest.mark.parametrize("race", [_race_existing_stream, _race_no_stream])
async def test_concurrent_appends_at_same_expected_version(race: Any) -> None:  # noqa: ANN401
    kind, inner = await _client()
    timed = Timed(inner)
    outcomes: Counter[str] = Counter()
    overlaps = 0
    max_version = 0
    for _ in range(N):
        outcome, overlapped, version = await race(timed)
        outcomes[outcome] += 1
        overlaps += overlapped
        max_version = max(max_version, version)
    print(f"\nEXP1 {kind} {race.__name__}: N={N} overlapped={overlaps} "
          f"max_final_version={max_version} outcomes={dict(outcomes)}")
    double = sum(v for k, v in outcomes.items() if k.startswith("ok=2"))
    assert double == 0, f"BOTH appends succeeded {double} times"


async def test_harness_can_see_a_double_success_memory() -> None:
    """Mutation: drop expected_version. The harness MUST then report ok=2,
    otherwise a green run above could be the harness being blind."""
    timed = Timed(MemoryEventStoreClient(), drop_expected_version=True)
    outcome, _, version = await _race_existing_stream(timed)
    assert timed.mutated_calls >= 3  # save_new + two saves all went through the mutation
    print(f"\nEXP1 mutation(memory, expected_version dropped): {outcome} final_version={version}")
    assert outcome.startswith("ok=2")


async def test_stream_exists_when_store_unreachable() -> None:
    """Guard 3 of the decision: 'a dispatcher that checks whether the stream
    exists before it dispatches'. What does exists() say when the store is down?"""
    from event_sourcing.client.grpc_client import GrpcEventStoreClient

    c = GrpcEventStoreClient(address="127.0.0.1:1", tenant_id="exp")  # nothing listens here
    await c.connect()
    exists = await c.stream_exists("WorkflowExecution-exec-anything")
    repo = EventStoreRepository(c, WorkflowExecutionAggregate, "WorkflowExecution")
    try:
        repo_exists: object = await repo.exists("exec-anything")
    except Exception as exc:  # noqa: BLE001
        repo_exists = f"raised {type(exc).__name__}"
    print(f"\nEXP1 store unreachable: client.stream_exists={exists} repository.exists={repo_exists}")
