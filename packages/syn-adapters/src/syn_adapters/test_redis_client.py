"""The retry must actually retry, not merely be configured.

Asserting that `socket_timeout == 5.0` only proves the literal was typed. The
failure this closes (#1078) is a read that timed out and killed a phase mid-run,
so the test that matters is behavioural: a transient TimeoutError must be
survived, and a persistent one must still be reported rather than hung on.
"""

from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from syn_adapters.redis_client import MAX_RETRIES, resilient_redis_client


async def _ignore(_error: BaseException) -> None:
    """redis-py awaits the failure handler, so it must be a coroutine."""
    return None


pytestmark = pytest.mark.unit

_URL = "redis://localhost:6379/0"


class TestTransientFailureIsSurvived:
    """The exact shape that killed exec-27755c0030bd and exec-6a27907cadcd."""

    async def test_a_read_that_times_out_once_still_succeeds(self) -> None:
        attempts: list[int] = []

        async def times_out_then_works() -> str:
            attempts.append(1)
            if len(attempts) == 1:
                raise RedisTimeoutError("Timeout reading from redis:6379")
            return "value"

        retry = resilient_redis_client(_URL).get_retry()
        result = await retry.call_with_retry(times_out_then_works, _ignore)

        assert result == "value"
        assert len(attempts) == 2, "the timeout should have been retried exactly once"

    async def test_a_connection_error_is_retried_too(self) -> None:
        """A dropped connection is the same class of blip as a slow read."""
        attempts: list[int] = []

        async def drops_then_works() -> str:
            attempts.append(1)
            if len(attempts) == 1:
                raise RedisConnectionError("connection reset")
            return "value"

        retry = resilient_redis_client(_URL).get_retry()
        assert await retry.call_with_retry(drops_then_works, _ignore) == "value"
        assert len(attempts) == 2

    async def test_it_survives_failures_up_to_the_configured_limit(self) -> None:
        """MAX_RETRIES is a real budget, not decoration."""
        attempts: list[int] = []

        async def fails_then_works() -> str:
            attempts.append(1)
            if len(attempts) <= MAX_RETRIES:
                raise RedisTimeoutError("still stalling")
            return "value"

        retry = resilient_redis_client(_URL).get_retry()
        assert await retry.call_with_retry(fails_then_works, _ignore) == "value"
        assert len(attempts) == MAX_RETRIES + 1


class TestPersistentFailureStillRaises:
    """A retry must not turn a dead dependency into a hang or a silent success."""

    async def test_a_dead_redis_is_reported(self) -> None:
        attempts: list[int] = []

        async def always_times_out() -> str:
            attempts.append(1)
            raise RedisTimeoutError("redis is gone")

        retry = resilient_redis_client(_URL).get_retry()
        with pytest.raises(RedisTimeoutError):
            await retry.call_with_retry(always_times_out, _ignore)

        assert len(attempts) == MAX_RETRIES + 1, "must stop trying, not loop forever"


class TestBoundedWaiting:
    """redis-py's default socket_timeout is None - wait forever.

    That default is what let a stalled read block a phase, so the fix is void
    if the timeouts are ever dropped.
    """

    def test_reads_and_connects_are_bounded(self) -> None:
        kwargs = resilient_redis_client(_URL).get_connection_kwargs()
        socket_timeout = kwargs.get("socket_timeout")
        connect_timeout = kwargs.get("socket_connect_timeout")

        assert socket_timeout is not None, "an unbounded read can block a phase forever"
        assert connect_timeout is not None
        assert 0 < float(socket_timeout) <= 30
        assert 0 < float(connect_timeout) <= 30

    def test_timeouts_are_in_the_retried_error_set(self) -> None:
        """Pins a default we rely on rather than a behaviour we added.

        redis-py 7.4's `Retry` already treats TimeoutError as retryable, so
        removing `retry_on_error` does NOT currently break the retry - the
        behavioural tests above still pass without it. This test exists so that
        if upstream ever narrows that default, it fails here instead of in a
        production phase.
        """
        retried = resilient_redis_client(_URL).get_connection_kwargs().get("retry_on_error") or []
        assert RedisTimeoutError in retried, "the motivating failure would not be retried"
