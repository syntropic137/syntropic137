"""Durable maintenance mode, backed by Redis (#1387, ADR-060).

The Redis tier of the ADR-060 chain, for deployments with no observability
database. One key, no TTL: an expiring admission gate would re-open admission
on its own, which is the same failure as losing it on restart, just later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts._shared import MaintenanceMode

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

__all__ = ["RedisMaintenanceAdapter"]

_KEY = "syn:maintenance:mode"


class RedisMaintenanceAdapter:
    """Redis-backed maintenance mode.

    Implements
    :class:`~syn_domain.contexts._shared.maintenance.MaintenancePort`.
    """

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def current(self) -> MaintenanceMode:
        """Read the stored state on every call - nothing here is cached."""
        raw: bytes | str | None = await self._redis.get(_KEY)
        if raw is None:
            return MaintenanceMode()
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            return MaintenanceMode.model_validate_json(text)
        except ValueError:
            # A key we cannot parse is a key we cannot trust to mean "open".
            # Refusing admission delays a deploy; assuming open loses an
            # execution, which is what this gate exists to prevent.
            return MaintenanceMode(
                active=True,
                reason="stored maintenance state is unreadable",
                since=None,
                actor="",
            )

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        """Persist the state, then return it. Written before this returns."""
        mode = MaintenanceMode(
            active=active,
            reason=reason,
            since=datetime.now(UTC) if active else None,
            actor=actor,
        )
        await self._redis.set(_KEY, mode.model_dump_json())
        return mode
