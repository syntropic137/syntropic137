"""The execution budget's own rules: FIFO, no barging, no duplicates, no leaks (#1557)."""

from __future__ import annotations

import asyncio

import pytest

from syn_api.execution_budget import (
    ExecutionBudget,
    StartAlreadyClaimedError,
    StartClaim,
    StartPath,
)

pytestmark = pytest.mark.unit


def _claim(budget: ExecutionBudget, execution_id: str) -> StartClaim:
    return budget.claim(execution_id, workflow_id="wf", path=StartPath.DIRECT)


async def test_waiters_start_in_the_order_they_arrived() -> None:
    budget = ExecutionBudget(1)
    first = _claim(budget, "exec-1")
    order: list[str] = []

    async def run(execution_id: str) -> None:
        async with budget.held(budget.position(execution_id).claim):  # type: ignore[union-attr]
            order.append(execution_id)

    waiting = [_claim(budget, f"exec-{n}") for n in (2, 3, 4)]
    tasks = [asyncio.create_task(run(c.execution_id)) for c in reversed(waiting)]
    await asyncio.sleep(0)
    assert [budget.position(c.execution_id).position for c in waiting] == [1, 2, 3]  # type: ignore[union-attr]

    budget.release(first)
    await asyncio.gather(*tasks)

    assert order == ["exec-2", "exec-3", "exec-4"]


async def test_a_new_claim_never_barges_past_the_queue() -> None:
    budget = ExecutionBudget(1)
    first = _claim(budget, "exec-1")
    _claim(budget, "exec-2")
    budget.release(first)
    late = _claim(budget, "exec-3")

    assert budget.position("exec-2").position is None  # type: ignore[union-attr]
    assert budget.position(late.execution_id).position == 1  # type: ignore[union-attr]


async def test_the_same_execution_cannot_claim_twice() -> None:
    budget = ExecutionBudget(1)
    _claim(budget, "exec-1")
    _claim(budget, "exec-2")

    with pytest.raises(StartAlreadyClaimedError):
        _claim(budget, "exec-2")


async def test_a_start_cancelled_while_queued_gives_its_place_back() -> None:
    budget = ExecutionBudget(1)
    _claim(budget, "exec-1")
    queued = _claim(budget, "exec-2")

    async def wait() -> None:
        async with budget.held(queued):
            pytest.fail("a cancelled start must never get a slot")

    task = asyncio.create_task(wait())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert budget.position("exec-2") is None
    behind = _claim(budget, "exec-3")
    assert budget.position(behind.execution_id).position == 1  # type: ignore[union-attr]


async def test_release_is_idempotent_and_a_stale_claim_releases_nothing() -> None:
    budget = ExecutionBudget(1)
    old = _claim(budget, "exec-1")
    budget.release(old)
    budget.release(old)
    new = _claim(budget, "exec-1")

    budget.release(old)

    assert budget.position("exec-1") is not None
    assert budget.position("exec-1").claim is new  # type: ignore[union-attr]


def test_a_budget_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ExecutionBudget(0)
