"""Gate process dispatch on durable intent and retain abnormal attempt outcomes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import InvocationStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .SessionLifecycleManager import SessionLifecycleManager


@asynccontextmanager
async def registered_attempt(
    manager: SessionLifecycleManager | None,
    harness: str,
) -> AsyncIterator[None]:
    if manager is not None:
        await manager.prepare_invocation(harness)
    try:
        yield
    except asyncio.CancelledError:
        if manager is not None:
            await manager.finish_invocation(
                native_session_id=None, status=InvocationStatus.CANCELLED
            )
        raise
    except Exception:
        if manager is not None:
            await manager.finish_invocation(native_session_id=None, status=InvocationStatus.FAILED)
        raise
