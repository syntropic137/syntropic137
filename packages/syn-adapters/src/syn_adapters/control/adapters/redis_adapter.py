"""Redis-backed signal queue adapter for production use.

Signals are stored as short-lived Redis keys so they survive inter-process
communication and are automatically cleaned up if never consumed.

Key design decisions:
- One signal per execution (last-write-wins — cancel always overrides pause)
- GETDEL for atomic read-and-remove (signal consumed exactly once)
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


class RedisSignalQueueAdapter:
    """Redis-backed signal queue for production deployments.

    Stores one pending signal per execution_id. The execution engine consumes
    the signal atomically (GETDEL), so it is processed exactly once.

    Implements SignalQueuePort protocol.

    Args:
        redis: An async Redis client instance.
    """

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    def _key(self, execution_id: str) -> str:
        return f"{_KEY_PREFIX}{execution_id}"

    async def enqueue(self, execution_id: str, signal: ControlSignal) -> None:
        """Store a signal for the given execution.

        Overwrites any existing pending signal (cancel wins over pause).
        """
        payload = json.dumps({
            "signal_type": signal.signal_type,
            "execution_id": signal.execution_id,
            "reason": signal.reason,
            "inject_message": signal.inject_message,
        })
        await self._redis.set(self._key(execution_id), payload, ex=_SIGNAL_TTL_SECONDS)
        logger.debug("Enqueued signal type=%s for execution %s", signal.signal_type, execution_id)

    async def dequeue(self, execution_id: str) -> ControlSignal | None:
        """Atomically read and remove the pending signal, or None if absent."""
        raw = await self._redis.getdel(self._key(execution_id))
        if raw is None:
            return None
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
