"""The maintenance flag has to outlive the container that set it (#1387).

The deploy sequence is: set the flag, drain, swap, clear. The swap destroys the
API container. If the flag lived in that container's memory, the replacement
would come up admitting executions in the middle of the deploy it was set for,
and nothing would report it - which is the ADR-060 failure, and the reason
these tests build a SECOND adapter over the same store rather than asking the
first one what it remembers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

import pytest

from syn_adapters.maintenance import (
    InMemoryMaintenanceAdapter,
    PostgresMaintenanceAdapter,
    RedisMaintenanceAdapter,
)
from syn_adapters.maintenance.postgres_maintenance import CURRENT_SQL, SET_MODE_SQL

if TYPE_CHECKING:
    from datetime import datetime

pytestmark = pytest.mark.unit


class _StoredRow(TypedDict, total=False):
    """The one row ``maintenance_mode`` holds, as asyncpg hands it back.

    Named keys rather than an untyped mapping, so the double and the adapter
    cannot drift: the adapter reads these four by name, and a fake agreeing
    only in shape would still pass while spelling one of them differently.
    """

    active: bool
    reason: str | None
    since: datetime | None
    actor: str | None


class _FakeRedis:
    """A Redis that survives its client. Shared across adapter instances."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value


class _FakeConnection:
    def __init__(self, store: _StoredRow) -> None:
        self._store = store

    async def execute(self, query: str, *args: object) -> str:
        if query is SET_MODE_SQL or "INSERT INTO maintenance_mode" in query:
            active, reason, since, actor = args
            self._store.update(
                cast(
                    "_StoredRow",
                    {"active": active, "reason": reason, "since": since, "actor": actor},
                )
            )
        return "OK"

    async def fetchrow(self, query: str, *args: object) -> _StoredRow | None:
        assert query is CURRENT_SQL or "SELECT" in query
        return self._store.copy() if self._store else None


class _FakePool:
    """A database that survives its pool. Shared across adapter instances."""

    def __init__(self) -> None:
        self.rows: _StoredRow = {}

    def acquire(self) -> _FakePoolAcquire:
        return _FakePoolAcquire(self.rows)


class _FakePoolAcquire:
    def __init__(self, rows: _StoredRow) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeConnection:
        return _FakeConnection(self._rows)

    async def __aexit__(self, *_exc: object) -> None:
        return None


class TestTheFlagSurvivesTheContainerThatSetIt:
    """A fresh adapter over the same store is a restarted API container."""

    async def test_redis_adapter_restart_still_refuses(self) -> None:
        backend = _FakeRedis()
        await RedisMaintenanceAdapter(backend).set_mode(  # type: ignore[arg-type]
            active=True, reason="pit stop 0.29.1", actor="deploy-script"
        )

        restarted = await RedisMaintenanceAdapter(backend).current()  # type: ignore[arg-type]

        assert restarted.active is True
        assert restarted.reason == "pit stop 0.29.1"
        assert restarted.actor == "deploy-script"
        assert restarted.since is not None

    async def test_postgres_adapter_restart_still_refuses(self) -> None:
        pool = _FakePool()
        await PostgresMaintenanceAdapter(pool).set_mode(  # type: ignore[arg-type]
            active=True, reason="pit stop 0.29.1", actor="deploy-script"
        )

        restarted = await PostgresMaintenanceAdapter(pool).current()  # type: ignore[arg-type]

        assert restarted.active is True
        assert restarted.reason == "pit stop 0.29.1"
        assert restarted.since is not None

    async def test_redis_adapter_restart_after_clear_admits_again(self) -> None:
        """The far side of the swap. A gate that cannot be reopened is an outage."""
        backend = _FakeRedis()
        adapter = RedisMaintenanceAdapter(backend)  # type: ignore[arg-type]
        await adapter.set_mode(active=True, reason="pit stop", actor="deploy-script")
        await adapter.set_mode(active=False, reason="", actor="deploy-script")

        restarted = await RedisMaintenanceAdapter(backend).current()  # type: ignore[arg-type]

        assert restarted.active is False
        assert restarted.since is None

    async def test_postgres_adapter_restart_after_clear_admits_again(self) -> None:
        pool = _FakePool()
        adapter = PostgresMaintenanceAdapter(pool)  # type: ignore[arg-type]
        await adapter.set_mode(active=True, reason="pit stop", actor="deploy-script")
        await adapter.set_mode(active=False, reason="", actor="deploy-script")

        restarted = await PostgresMaintenanceAdapter(pool).current()  # type: ignore[arg-type]

        assert restarted.active is False
        assert restarted.since is None


class TestAnUnwrittenStoreReadsAsOpen:
    """Nobody has to set "admission open" for admission to be open."""

    async def test_redis(self) -> None:
        assert (await RedisMaintenanceAdapter(_FakeRedis()).current()).active is False  # type: ignore[arg-type]

    async def test_postgres(self) -> None:
        assert (await PostgresMaintenanceAdapter(_FakePool()).current()).active is False  # type: ignore[arg-type]

    async def test_memory(self) -> None:
        assert (await InMemoryMaintenanceAdapter().current()).active is False


class TestStateWeCannotReadIsNotTreatedAsOpen:
    async def test_redis_corrupt_value_refuses(self) -> None:
        """Guessing "open" loses an execution; guessing "closed" delays a deploy."""
        backend = _FakeRedis()
        backend.data["syn:maintenance:mode"] = "{not json"

        mode = await RedisMaintenanceAdapter(backend).current()  # type: ignore[arg-type]

        assert mode.active is True
        assert "unreadable" in mode.reason
