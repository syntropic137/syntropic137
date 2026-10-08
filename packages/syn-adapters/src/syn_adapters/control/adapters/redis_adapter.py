"""Redis-backed signal queue adapter for production use.

Signals are stored as short-lived Redis keys so they survive inter-process
communication and are automatically cleaned up if never consumed.

Key design decisions:
- One signal per execution (last-write-wins — cancel always overrides pause)
- Consume moves the signal to a per-execution claim key and returns it, in
  one Lua script; a separate DEL acknowledges it. Delivery is AT LEAST ONCE
  (#1756), see ``dequeue``
- TTL of 5 minutes: long enough for slow engines, short enough to self-clean
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

    from syn_adapters.control.commands import ControlSignal

logger = logging.getLogger(__name__)

_SIGNAL_TTL_SECONDS = 300  # 5 minutes
_KEY_PREFIX = "syn:signal:"
_CLAIM_PREFIX = "syn:signal-claim:"

# KEYS[1] signal, KEYS[2] claim, ARGV[1] claim TTL. An unacknowledged claim
# is returned again rather than a newer signal being taken, so running this
# twice (a retried EVALSHA whose first reply was lost) returns the same signal.
_CLAIM_SCRIPT = """
local claimed = redis.call('GET', KEYS[2])
if claimed then return claimed end
local signal = redis.call('GETDEL', KEYS[1])
if signal then redis.call('SET', KEYS[2], signal, 'EX', ARGV[1]) end
return signal
"""


class RedisSignalQueueAdapter:
    """Redis-backed signal queue for production deployments.

    Stores one pending signal per execution_id. Delivery is at least once:
    a signal is never lost to a reply that did not arrive, and may be
    delivered twice when its acknowledgement does not land.

    Implements SignalQueuePort protocol.

    Args:
        redis: An async Redis client instance.
    """

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis
        self._claim = redis.register_script(_CLAIM_SCRIPT)

    def _key(self, execution_id: str) -> str:
        return f"{_KEY_PREFIX}{execution_id}"

    def _claim_key(self, execution_id: str) -> str:
        return f"{_CLAIM_PREFIX}{execution_id}"

    async def enqueue(self, execution_id: str, signal: ControlSignal) -> None:
        """Store a signal for the given execution.

        Overwrites any existing pending signal (cancel wins over pause).
        """
        payload = json.dumps(
            {
                "signal_type": signal.signal_type,
                "execution_id": signal.execution_id,
                "reason": signal.reason,
                "inject_message": signal.inject_message,
            }
        )
        await self._redis.set(self._key(execution_id), payload, ex=_SIGNAL_TTL_SECONDS)
        logger.debug("Enqueued signal type=%s for execution %s", signal.signal_type, execution_id)

    async def dequeue(self, execution_id: str) -> ControlSignal | None:
        """Remove and return the pending signal, or None if absent.

        A bare GETDEL lost the signal whenever the server applied it and the
        reply did not arrive (#1756): the client retries such a command, and
        the retry found the key already gone. Instead the signal is claimed
        and only then acknowledged:

        1. the claim script moves the signal to a claim key and returns it,
           or returns the claim left by an earlier call that never
           acknowledged it. A retried claim therefore returns the same signal.
        2. once the signal is in hand, DEL of the claim key acknowledges it.
           DEL is idempotent, so its retry is harmless.

        If the acknowledgement fails, the next call delivers the same signal
        again: at least once, never zero. An unacknowledged claim expires
        with the same TTL as the signal.

        Fail-open on Redis errors (#1078): the signal queue is a
        control-plane read (pause/cancel/resume), not on the critical path
        of the work a phase is doing. A transient timeout here must be
        treated the same as "no signal pending", not propagate and fail an
        otherwise-healthy phase - matching the fail-open stance the dedup
        adapter already takes when Redis is unavailable.
        """
        import redis.exceptions

        claim_key = self._claim_key(execution_id)
        try:
            raw: bytes | str | None = await self._claim(
                keys=[self._key(execution_id), claim_key], args=[_SIGNAL_TTL_SECONDS]
            )
        except redis.exceptions.RedisError:
            logger.warning(
                "Redis error reading signal for execution %s; treating as no signal pending",
                execution_id,
                exc_info=True,
            )
            return None
        if raw is None:
            return None
        try:
            await self._redis.delete(claim_key)
        except redis.exceptions.RedisError:
            logger.warning(
                "Redis error acknowledging signal for execution %s; it will be delivered again",
                execution_id,
                exc_info=True,
            )
        return self._deserialize(raw)

    async def get_signal(self, execution_id: str) -> ControlSignal | None:
        """Alias for dequeue — consume the next pending signal."""
        return await self.dequeue(execution_id)

    def _deserialize(self, raw: bytes | str) -> ControlSignal:
        from syn_adapters.control.commands import ControlSignal, ControlSignalType

        data = json.loads(raw)
        return ControlSignal(
            signal_type=ControlSignalType(data["signal_type"]),
            execution_id=data["execution_id"],
            reason=data.get("reason"),
            inject_message=data.get("inject_message"),
        )
