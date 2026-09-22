"""Gate process dispatch on durable intent and retain abnormal attempt outcomes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import InvocationStatus
from syn_shared.env_constants import ENV_AGENTIC_ATTEMPT_ID, ENV_AGENTIC_INVOCATION_ID

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions import SessionInvocationState

    from .SessionLifecycleManager import SessionLifecycleManager


@asynccontextmanager
async def registered_attempt(
    manager: SessionLifecycleManager | None,
    harness: str,
) -> AsyncIterator[SessionInvocationState | None]:
    invocation = await manager.prepare_invocation(harness) if manager is not None else None
    try:
        yield invocation
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


def invocation_environment(
    environment: dict[str, str], invocation: SessionInvocationState | None
) -> dict[str, str]:
    """Dispatch only the current durable registration, never inherited attempt IDs."""
    result = environment.copy()
    for key in (ENV_AGENTIC_INVOCATION_ID, ENV_AGENTIC_ATTEMPT_ID):
        result.pop(key, None)
    if invocation is not None:
        result[ENV_AGENTIC_INVOCATION_ID] = invocation.invocation_id
        result[ENV_AGENTIC_ATTEMPT_ID] = invocation.attempt_id
    return result
