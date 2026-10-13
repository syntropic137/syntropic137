"""The in-memory store answers a keyed batch in one call, as Postgres does (#1816)."""

from __future__ import annotations

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.projection_scan import read_by_keys

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


async def test_read_by_keys_is_one_get_many_never_a_get_per_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryProjectionStore()
    await store.save("p", "a", {"v": 1})
    await store.save("p", "b", {"v": 2})

    async def no_per_key_get(projection: str, key: str) -> None:
        raise AssertionError(f"per-key get({projection!r}, {key!r})")

    monkeypatch.setattr(store, "get", no_per_key_get)

    found = await read_by_keys(store, "p", ["a", "b", "missing"])

    assert found == {"a": {"v": 1}, "b": {"v": 2}}
    assert await store.get_many("absent-projection", ["a"]) == {}
