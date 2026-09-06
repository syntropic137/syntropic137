"""One place that builds a Redis client, with the resilience settings set.

Both Redis clients in ``syn_api._wiring`` previously had none of this
(#1078): a transient read timeout on a control-plane call (dedup, signal
queue) raised straight out of stream processing and failed an
otherwise-healthy phase. Bounding the timeout and retrying narrows that
window; adapters that read through this client still need to decide how to
fail (open or closed) when retries are exhausted.
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
