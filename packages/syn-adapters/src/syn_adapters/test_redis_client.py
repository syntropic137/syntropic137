"""Tests for resilient Redis client construction (#1078).

Verifies that resilient_redis_client() actually attaches the retry and
timeout policy to the connection pool, rather than the kwargs being accepted
by from_url() and then silently dropped somewhere in construction.
"""

from __future__ import annotations

import pytest
from redis.asyncio.retry import Retry

from syn_adapters.redis_client import resilient_redis_client

pytestmark = pytest.mark.unit


def test_resilient_client_configures_connection_pool() -> None:
    """The timeout/retry policy reaches the connection pool, not just from_url()'s kwargs."""
    client = resilient_redis_client("redis://localhost:6379")

    pool_kwargs = client.connection_pool.connection_kwargs

    assert pool_kwargs["socket_timeout"] == 5.0
    assert pool_kwargs["socket_connect_timeout"] == 5.0
    assert pool_kwargs["retry_on_timeout"] is True
    assert isinstance(pool_kwargs["retry"], Retry)
    assert pool_kwargs["retry"]._retries == 3
