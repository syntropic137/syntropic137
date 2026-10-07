"""One contract, three dedup adapters (ADR-060).

The same assertions run against InMemoryDedupAdapter (unit) and the two
durable adapters production wires instead: RedisDedupAdapter and
PostgresDedupAdapter (integration, against the test stack). A dedup fake
that answers differently from the backend certifies duplicate or dropped
trigger fires that only production would show.

Integration needs the test stack: ``TEST_REDIS_URL`` (default
``redis://localhost:16379``) and ``TEST_DATABASE_URL`` (default the test
stack's TimescaleDB on 15432). Each skips, never passes, when its backend
does not answer.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from syn_adapters.dedup.memory_dedup import InMemoryDedupAdapter
from syn_adapters.dedup.postgres_dedup import PostgresDedupAdapter
from syn_adapters.dedup.redis_dedup import RedisDedupAdapter
from syn_shared.testing import (
    ENV_TEST_DATABASE_URL,
    ENV_TEST_REDIS_URL,
    TEST_STACK_PORTS,
    get_test_timescaledb_url,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DedupAdapter = InMemoryDedupAdapter | RedisDedupAdapter | PostgresDedupAdapter


def _require(url: str) -> None:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "", parsed.port or 0), timeout=1):
            return
    except OSError:
        pytest.skip(f"no backend at {parsed.hostname}:{parsed.port}")


@pytest.fixture(
    params=[
        pytest.param("memory", marks=pytest.mark.unit),
        pytest.param("redis", marks=pytest.mark.integration),
        pytest.param("postgres", marks=pytest.mark.integration),
    ]
)
async def dedup(request: pytest.FixtureRequest) -> AsyncIterator[DedupAdapter]:
    if request.param == "memory":
        yield InMemoryDedupAdapter()
    elif request.param == "redis":
        import redis.asyncio as aioredis

        url = os.getenv(ENV_TEST_REDIS_URL, f"redis://localhost:{TEST_STACK_PORTS['redis']}")
        _require(url)
        client = aioredis.Redis.from_url(url)
        yield RedisDedupAdapter(client)
        await client.aclose()
    else:
        import asyncpg

        url = os.getenv(ENV_TEST_DATABASE_URL, get_test_timescaledb_url())
        _require(url)
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
        adapter = PostgresDedupAdapter(pool)
        yield adapter
        if adapter._cleanup_task is not None:
            adapter._cleanup_task.cancel()
        await pool.close()


def _key() -> str:
    return f"contract:{uuid4().hex}"


async def test_first_sighting_is_new_and_second_is_duplicate(dedup: DedupAdapter) -> None:
    key = _key()
    assert await dedup.is_duplicate(key) is False
    assert await dedup.is_duplicate(key) is True


async def test_mark_seen_makes_the_next_sighting_a_duplicate(dedup: DedupAdapter) -> None:
    key = _key()
    await dedup.mark_seen(key)
    assert await dedup.is_duplicate(key) is True


async def test_mark_seen_twice_is_harmless(dedup: DedupAdapter) -> None:
    key = _key()
    await dedup.mark_seen(key)
    await dedup.mark_seen(key)
    assert await dedup.is_duplicate(key) is True


async def test_keys_are_independent(dedup: DedupAdapter) -> None:
    first, second = _key(), _key()
    assert await dedup.is_duplicate(first) is False
    assert await dedup.is_duplicate(second) is False
