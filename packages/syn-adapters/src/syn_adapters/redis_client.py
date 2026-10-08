"""One place that builds a Redis client, with the resilience settings set.

Both Redis clients in ``syn_api._wiring`` previously had none of this
(#1078): a transient read timeout on a control-plane call (dedup, signal
queue) raised straight out of stream processing and failed an
otherwise-healthy phase. Bounding the timeout and retrying narrows that
window; adapters that read through this client still need to decide how to
fail (open or closed) when retries are exhausted.

The retry resends a command whose reply did not arrive, on a timeout or on a
connection error while reading. Redis may already have applied it. So **every
command sent through this client can run more than once**, and an adapter
whose command is not idempotent must make the repeat harmless itself (#1756).
Narrowing the retried errors would not help: a connection that drops after
the send has the same "applied, reply lost" ambiguity as a timeout. See
``RedisDedupAdapter.is_duplicate`` (per-call token) and
``RedisSignalQueueAdapter.dequeue`` (claim, then acknowledge).
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff


def resilient_redis_client(url: str, *, decode_responses: bool = True) -> Redis:
    """Build a Redis client with bounded timeouts and a retry policy.

    Args:
        url: Redis connection URL.
        decode_responses: Return ``str`` rather than ``bytes``. Both current
            callers want this; it is a parameter so a future binary caller
            is not forced to rebuild the retry policy to opt out.
    """
    return Redis.from_url(
        url,
        decode_responses=decode_responses,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=True,
        retry=Retry(ExponentialBackoff(), retries=3),
    )
