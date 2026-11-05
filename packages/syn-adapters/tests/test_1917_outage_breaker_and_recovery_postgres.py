"""Real-Postgres acceptance for the Outage Breaker and the Recovery Kit (#1917 slice 2).

The breaker disables an executor's claims after consecutive failed creates,
never by lowering capacity, so the D3 ``CHECK`` holds while runs are charged.
A dead E2B executor's run is fenced and reaped only by an executor holding a
Recovery Kit for its account (C8, ADR-072 D5); a failed list or kill keeps it
``fencing`` and charged. The E2B account is a ``SandboxDouble``, never E2B.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import asyncpg
import pytest
from agentic_isolation import E2BWorkspaceProvider
from agentic_isolation.providers.e2b_client import E2BTransportError, SandboxListing

# The #1310 fixture and helpers: four asyncpg connection pools on one fresh schema.
from test_execution_run_queue_postgres import (  # noqa: F401
    _budget,
    _expire_claims,
    _Interrupter,
    _reconcile,
    _state,
    pools,
)

from syn_adapters.execution_host.reconciler import Reconciler
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.workspace_backends.e2b.recovery_kit import (
    LABEL_EXECUTION_ID,
    E2BRecoveryKit,
    E2BRunReaper,
)
from syn_adapters.workspace_backends.e2b.test_e2b_backend import SandboxDouble
from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_domain.contexts.orchestration.ports import (
    ExecutorHost,
    ExecutorPool,
    IsolationLevel,
    RunWorkload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.integration

E2B_SCOPE = "e2b-key-0123456789abcdef"
LOCAL = ExecutorPool(pool_id="local", priority=0, provider="docker")
E2B = ExecutorPool(
    pool_id="e2b",
    priority=2,
    provider="e2b",
    isolation=IsolationLevel.MICROVM,
    supplies_credentials=False,
    overflow_delay=timedelta(0),
    overflow_budget_usd_per_day=50,
)
_COOLDOWN = timedelta(minutes=5)


def _executor(
    host_id: str,
    pool: ExecutorPool,
    scope: str,
    *,
    recovery: frozenset[str] = frozenset(),
) -> ExecutorHost:
    return ExecutorHost(
        host_id=host_id,
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=1,
        reap_scope=scope,
        pool=pool,
        recovery_scopes=recovery,
    )


async def _join(queue: PostgresExecutionRunQueue, host: ExecutorHost, capacity: int) -> None:
    await queue.register(host, capacity)
    await queue.heartbeat(host.host_id)


async def _admit(queue: PostgresExecutionRunQueue, *ids: str) -> None:
    for execution_id in ids:
        assert await queue.reserve(execution_id, 1, is_resume=False, workload=RunWorkload.SCRIPTED)
        await queue.mark_admitted(execution_id)


async def _row(pool: asyncpg.Pool, executor_id: str) -> tuple[int, int, int, bool]:
    """``capacity``, ``in_use``, ``create_failures`` and whether claims are disabled now."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT capacity,in_use,create_failures,
                COALESCE(claims_disabled_until>clock_timestamp(),FALSE) AS disabled
            FROM execution_budget WHERE executor_id=$1""",
            executor_id,
        )
    assert row is not None
    return (row["capacity"], row["in_use"], row["create_failures"], row["disabled"])


async def _trip(queue: PostgresExecutionRunQueue, host_id: str, times: int = 3) -> list[bool]:
    return [
        await queue.record_create_failure(host_id, threshold=3, cooldown=_COOLDOWN)
        for _ in range(times)
    ]


# --- Outage Breaker ------------------------------------------------------------


async def test_the_breaker_disables_claims_while_runs_are_charged_and_the_check_holds(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, _executor("e2b-1", E2B, E2B_SCOPE), capacity=3)
    await _admit(queue, "run-1", "run-2", "run-3")
    held = await queue.claim("e2b-1")
    assert held is not None

    assert await _trip(queue, "e2b-1") == [False, False, True]

    assert await queue.claim("e2b-1") is None
    assert await _state(pools[0], "run-2") == "admitted"
    # Capacity untouched, the charge kept, and the CHECK still holds.
    assert await _row(pools[0], "e2b-1") == (3, 1, 3, True)
    # The rejected alternative: capacity 0 is refused while a run is charged.
    async with pools[0].acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("UPDATE execution_budget SET capacity=0 WHERE executor_id='e2b-1'")
    # A charged run still finishes normally under a disabled breaker.
    await queue.close(held)
    assert await _row(pools[0], "e2b-1") == (3, 0, 3, True)


async def test_a_disabled_executor_stamps_no_claim_check_and_holds_no_lower_pool_back(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    """A disabled executor advertises no room, so lower pools overflow past it at once."""
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, _executor("local-1", LOCAL, "engine-1"), capacity=2)
    await _join(queue, _executor("e2b-1", E2B, E2B_SCOPE), capacity=2)
    assert await queue.claim("local-1") is None  # a fresh Claim Check with room
    stamp = await _claim_check(pools[0], "local-1")
    await _trip(queue, "local-1")
    await _admit(queue, "run-1")

    assert await queue.claim("local-1") is None
    assert await _claim_check(pools[0], "local-1") == stamp
    claimed = await queue.claim("e2b-1")
    assert claimed is not None
    assert (claimed.execution_id, claimed.pool_id, claimed.overflowed) == ("run-1", "e2b", False)


async def _claim_check(pool: asyncpg.Pool, executor_id: str) -> object:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT claim_checked_at FROM execution_budget WHERE executor_id=$1", executor_id
        )


async def test_after_the_cooldown_one_failure_retrips_at_once_and_a_success_clears(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, _executor("e2b-1", E2B, E2B_SCOPE), capacity=3)
    await _admit(queue, "run-1", "run-2", "run-3")
    await _trip(queue, "e2b-1")
    async with pools[0].acquire() as conn:
        await conn.execute(
            """UPDATE execution_budget SET claims_disabled_until=clock_timestamp()-interval '1 s'
            WHERE executor_id='e2b-1'"""
        )

    assert await queue.claim("e2b-1") is not None  # half-open: one claim is tried
    assert await queue.claim("e2b-1") is None  # and only one, until its create reports
    async with pools[0].acquire() as conn:  # a probe abandoned for a cooldown frees the next
        await conn.execute(
            """UPDATE execution_budget SET claims_disabled_until=clock_timestamp()-interval '1 s'
            WHERE executor_id='e2b-1'"""
        )
    assert await queue.claim("e2b-1") is not None
    assert await _trip(queue, "e2b-1", times=1) == [True]
    assert await queue.claim("e2b-1") is None

    await queue.record_create_success("e2b-1")
    assert await _row(pools[0], "e2b-1") == (3, 2, 0, False)
    assert await queue.claim("e2b-1") is not None


async def test_concurrent_failures_each_count_and_the_threshold_trips_once(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, _executor("e2b-1", E2B, E2B_SCOPE), capacity=1)

    tripped = await asyncio.gather(
        *(
            PostgresExecutionRunQueue(p).record_create_failure(
                "e2b-1", threshold=4, cooldown=_COOLDOWN
            )
            for p in pools
        )
    )

    assert sorted(tripped) == [False, False, False, True]
    assert await _row(pools[0], "e2b-1") == (1, 0, 4, True)


# --- Recovery Kit and the C8 fence guard ---------------------------------------


class _E2BAccount(SandboxDouble):
    """An E2B account whose list or kill can be failed, as in an outage."""

    def __init__(self, *, failing: str | None = None) -> None:
        super().__init__()
        self.failing = failing

    async def list(self, metadata: Mapping[str, str]) -> list[SandboxListing]:
        if self.failing == "list":
            raise E2BTransportError("E2B list unreachable")
        return await super().list(metadata)

    async def kill(self, sandbox_id: str) -> bool:
        if self.failing == "kill":
            raise E2BTransportError("E2B kill unreachable")
        return await super().kill(sandbox_id)


def _kit_reaper(account: _E2BAccount) -> E2BRunReaper:
    return E2BRunReaper(E2BRecoveryKit(E2BWorkspaceProvider("unused", client=account), E2B_SCOPE))


async def _dead_e2b_executor_with_a_sandbox(
    queue: PostgresExecutionRunQueue, pool: asyncpg.Pool, account: _E2BAccount
) -> None:
    """The E2B executor claimed ``run-1``, created its sandbox, then died."""
    await _join(queue, _executor("e2b-1", E2B, E2B_SCOPE), capacity=2)
    await _admit(queue, "run-1")
    assert await queue.claim("e2b-1") is not None
    await account.create(
        template="t",
        metadata={LABEL_HOST_ID: "e2b-1", LABEL_EXECUTION_ID: "run-1"},
        lifetime_seconds=60,
    )
    # Another run's sandbox on the same account is never touched.
    await account.create(
        template="t",
        metadata={LABEL_HOST_ID: "e2b-1", LABEL_EXECUTION_ID: "run-other"},
        lifetime_seconds=60,
    )
    await _expire_claims(pool, "e2b-1", expected=1)


async def test_a_dead_e2b_executor_is_reconciled_by_a_local_executor_holding_the_kit(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    account = _E2BAccount()
    await _dead_e2b_executor_with_a_sandbox(queue, pools[0], account)
    await _join(
        queue,
        _executor("local-1", LOCAL, "engine-1", recovery=frozenset({E2B_SCOPE})),
        capacity=2,
    )
    own = _Reaper("engine-1")
    interrupter = _Interrupter()
    reconciler = Reconciler(queue, "local-1", own, interrupter, kits=(_kit_reaper(account),))

    await _reconcile(reconciler)

    assert await _state(pools[0], "run-1") == "interrupted"
    assert interrupter.calls == ["run-1"]
    assert await _budget(pools[0], "e2b-1") == 0
    assert own.calls == []  # the local Docker reaper is never asked about a sandbox
    assert [labels[LABEL_EXECUTION_ID] for labels, _ in account.sandboxes.values()] == ["run-other"]


@pytest.mark.parametrize("failing", ["list", "kill"])
async def test_a_failed_list_or_kill_keeps_fencing_and_the_charge(
    pools: list[asyncpg.Pool],  # noqa: F811
    failing: str,
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    account = _E2BAccount()
    await _dead_e2b_executor_with_a_sandbox(queue, pools[0], account)
    await _join(
        queue,
        _executor("local-1", LOCAL, "engine-1", recovery=frozenset({E2B_SCOPE})),
        capacity=2,
    )
    account.failing = failing
    interrupter = _Interrupter()
    reconciler = Reconciler(
        queue, "local-1", _Reaper("engine-1"), interrupter, kits=(_kit_reaper(account),)
    )

    await _reconcile(reconciler)

    assert await _state(pools[0], "run-1") == "fencing"
    assert await _budget(pools[0], "e2b-1") == 1
    assert interrupter.calls == []
    # Recovered: the next turn reaps and releases.
    account.failing = None
    await _reconcile(reconciler)
    assert await _state(pools[0], "run-1") == "interrupted"
    assert await _budget(pools[0], "e2b-1") == 0


async def test_a_local_executor_without_the_kit_never_fences_the_run(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    """Negative control: same queue, same dead run; only the kit differs."""
    queue = PostgresExecutionRunQueue(pools[0])
    account = _E2BAccount()
    await _dead_e2b_executor_with_a_sandbox(queue, pools[0], account)
    await _join(queue, _executor("bare", LOCAL, "engine-1"), capacity=2)
    await _join(
        queue,
        _executor("other-kit", LOCAL, "engine-1", recovery=frozenset({"e2b-key-another"})),
        capacity=2,
    )

    assert await queue.fence_expired("bare", limit=10) == []
    assert await queue.fence_expired("other-kit", limit=10) == []
    assert await _state(pools[0], "run-1") == "claimed"
    assert await _budget(pools[0], "e2b-1") == 1
    assert len(account.sandboxes) == 2

    # Takeover keeps the same rule: a kit holder fences, leaves; a bare host never adopts.
    await _join(
        queue,
        _executor("kit", LOCAL, "engine-1", recovery=frozenset({E2B_SCOPE})),
        capacity=2,
    )
    (fenced,) = await queue.fence_expired("kit", limit=10)
    assert fenced.claimer_scope == E2B_SCOPE
    await queue.deregister("kit")
    assert await queue.take_over("bare", limit=10) == []
    assert await _state(pools[0], "run-1") == "fencing"


class _Reaper:
    """This host's own backend: never shown a sandbox."""

    def __init__(self, scope: str) -> None:
        self._scope = scope
        self.calls: list[tuple[str, str]] = []

    def scope(self) -> str:
        return self._scope

    def provider(self) -> str:
        return "docker"

    def isolation(self) -> IsolationLevel:
        return IsolationLevel.CONTAINER

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        self.calls.append((executor_id, execution_id))
        return True
