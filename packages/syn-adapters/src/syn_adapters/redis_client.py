"""One place that builds a Redis client, with the resilience settings set.

Both Redis call sites in the API were previously `aioredis.from_url(url,
decode_responses=True)` and nothing else: no retry policy, no bounded socket
timeout, no health check. A single slow read therefore surfaced as a fatal
error, and on 2026-09-02 that killed two `sdlc-implement-v1` phases outright:

    Timeout reading from redis:6379

One of them had run 962 seconds across 188 recorded operations. Its actual
work was proceeding correctly; a control-plane read timed out and the run was
discarded (issue #1078).

Redis here backs dedup keys and the pause/cancel/resume signal queue. Neither
is on the critical path of DOING the work, so a slow read on either has no
business destroying it.

WHAT THIS DOES AND DOES NOT FIX

This narrows the window: three retries with exponential backoff will ride out
a blip that a single attempt would not. It does NOT decide the larger question
of whether a control-plane read should be able to fail a phase at all. That is
a behavioural change in the callers, deliberately kept out of this module so
the two can be reviewed separately.

So a caller must still handle failure. The retry is a shock absorber, not a
guarantee.
"""

from __future__ import annotations

from typing import Final

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

#: Bounded so a hung read fails in seconds rather than blocking a phase.
#: redis-py's default is None, meaning "wait forever", which is the wrong
#: default for a control-plane dependency.
SOCKET_TIMEOUT_SECONDS: Final = 5.0
CONNECT_TIMEOUT_SECONDS: Final = 3.0

#: Three attempts over roughly 0.1s + 0.2s + 0.4s of backoff. Long enough to
#: cross a brief stall, short enough that a genuinely dead Redis is reported
#: promptly instead of hanging the caller.
MAX_RETRIES: Final = 3

#: Detects a connection that died while idle, before a caller tries to use it.
HEALTH_CHECK_INTERVAL_SECONDS: Final = 30


def resilient_redis_client(url: str, *, decode_responses: bool = True) -> Redis:
    """Build an async Redis client that survives a transient stall.

    Args:
        url: Redis connection URL.
        decode_responses: Return str rather than bytes. Both current callers
            want this; it is a parameter so a future binary caller is not
            forced to rebuild the retry policy to opt out.

    Returns:
        A configured client. Construction does not connect, so this cannot
        raise for an unreachable server - the first command will.
    """
    return Redis.from_url(
        url,
        decode_responses=decode_responses,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        health_check_interval=HEALTH_CHECK_INTERVAL_SECONDS,
        retry=Retry(ExponentialBackoff(), MAX_RETRIES),
        # Belt and braces, and deliberately redundant: `Retry`'s own default
        # supported_errors already covers both of these on redis-py 7.4. Naming
        # them at the client level pins the behaviour we depend on, so an
        # upstream change to that default surfaces as a failing test here
        # rather than as a phase dying in production again.
        retry_on_error=[RedisTimeoutError, RedisConnectionError],
    )
