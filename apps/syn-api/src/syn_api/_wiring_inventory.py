"""One durable inventory runtime per API process; no production memory fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from syn_adapters.session_inventory.runtime import create_inventory_runtime
from syn_adapters.storage.event_store_client import get_event_store_client
from syn_api._wiring_db import get_shared_db_pool
from syn_shared.settings import get_settings
from syn_shared.settings.workspace import WorkspaceSettings

if TYPE_CHECKING:
    from syn_adapters.session_inventory.database import Pool as InventoryPool
    from syn_adapters.session_inventory.runtime import InventoryRuntime

_runtime: InventoryRuntime | None = None


async def initialize_inventory_runtime() -> None:
    global _runtime
    if _runtime is not None:
        return
    pool = get_shared_db_pool()
    if pool is None:
        raise RuntimeError("session inventory requires a durable PostgreSQL backend")
    _runtime = await create_inventory_runtime(
        # asyncpg installs proxy methods dynamically; its stubs omit the
        # connection interface exercised by the real-Postgres contract tests.
        cast("InventoryPool", pool),
        get_event_store_client(),
        get_settings().session_inventory,
        recovery_image=WorkspaceSettings().docker_image,
    )


def get_inventory_runtime() -> InventoryRuntime:
    if _runtime is None:
        raise RuntimeError("session inventory runtime has not initialized")
    return _runtime


async def stop_inventory_runtime() -> None:
    global _runtime
    if _runtime is not None:
        await _runtime.clock.stop()
        if _runtime.replication is not None:
            await _runtime.replication.stop()
        _runtime = None
