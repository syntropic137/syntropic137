"""Integration tests for RedisDedupAdapter with real Redis via testcontainers.

Run with: uv run pytest -m integration packages/syn-adapters/tests/dedup/ -v
(set ``SYN_TEST_REDIS_URL`` to use a running Redis instead of Docker)
"""

from __future__ import annotations

import os
import re

import pytest

from syn_adapters.dedup.redis_dedup import RedisDedupAdapter

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_client():
    """Create a real Redis connection: ``SYN_TEST_REDIS_URL`` (flushed), else testcontainers."""
    import redis.asyncio as aioredis

    url = os.environ.get("SYN_TEST_REDIS_URL")
    if url:
        client = aioredis.Redis.from_url(url, decode_responses=True)
        await client.flushdb()
        yield client
        await client.flushdb()
        await client.aclose()
        return

    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as container:
        client = aioredis.Redis(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(6379)),
            decode_responses=True,
        )
        yield client
        await client.aclose()


@pytest.fixture
def dedup(redis_client) -> RedisDedupAdapter:
    """Create a RedisDedupAdapter with short TTL for testing."""
    return RedisDedupAdapter(redis=redis_client, ttl_seconds=10)


class TestRedisDedupIntegration:
    """Integration tests with real Redis — verifies atomic SETNX behavior."""

    @pytest.mark.asyncio
    async def test_first_key_is_not_duplicate(self, dedup: RedisDedupAdapter) -> None:
        assert await dedup.is_duplicate("key-1") is False

    @pytest.mark.asyncio
    async def test_second_same_key_is_duplicate(self, dedup: RedisDedupAdapter) -> None:
        await dedup.is_duplicate("key-dup")
        assert await dedup.is_duplicate("key-dup") is True

    @pytest.mark.asyncio
    async def test_different_keys_are_independent(self, dedup: RedisDedupAdapter) -> None:
        assert await dedup.is_duplicate("key-a") is False
        assert await dedup.is_duplicate("key-b") is False

    @pytest.mark.asyncio
    async def test_mark_seen_makes_subsequent_check_duplicate(
        self, dedup: RedisDedupAdapter
    ) -> None:
        await dedup.mark_seen("pre-marked")
        assert await dedup.is_duplicate("pre-marked") is True

    @pytest.mark.asyncio
    async def test_keys_have_correct_prefix(self, dedup: RedisDedupAdapter, redis_client) -> None:
        await dedup.is_duplicate("prefix-test")
        val = await redis_client.get("syn:dedup:prefix-test")
        # is_duplicate stores a per-call token (#1756), a uuid4 hex.
        assert val is not None and re.fullmatch(r"[0-9a-f]{32}", val)

    @pytest.mark.asyncio
    async def test_mark_seen_stores_marker(self, dedup: RedisDedupAdapter, redis_client) -> None:
        await dedup.mark_seen("marker-test")
        assert await redis_client.get("syn:dedup:marker-test") == "1"

    @pytest.mark.asyncio
    async def test_keys_have_ttl(self, dedup: RedisDedupAdapter, redis_client) -> None:
        await dedup.is_duplicate("ttl-test")
        ttl = await redis_client.ttl("syn:dedup:ttl-test")
        assert 0 < ttl <= 10
