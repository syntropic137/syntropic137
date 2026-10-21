"""An EVAL execute is judged on its body, and the grant must still be live after (#1744).

``authorize`` awaits the request body before it can tell whether an EVAL token
may launch. The token can expire, or teardown can revoke it, during that wait;
a verdict reached on a dead grant must not let the request through.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.platform_access import InMemoryPlatformTokenStore, PlatformTokenService
from syn_shared.platform_access import PlatformScope

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_PATH = "/workflows/wf-1/execute"
_BODY = json.dumps({"eval_id": "eval-own"}).encode()


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _setup() -> tuple[PlatformTokenService, _Clock, str]:
    clock = _Clock()
    service = PlatformTokenService(InMemoryPlatformTokenStore(), max_ttl_seconds=60, now=clock)
    token = await service.issue("exec-1", PlatformScope.EVAL, "eval-own")
    return service, clock, token


async def test_live_grant_with_own_eval_body_is_allowed() -> None:
    service, _, token = await _setup()

    async def body() -> bytes:
        return _BODY

    assert await service.authorize(f"Bearer {token}", "POST", _PATH, body) is None


async def test_token_expiring_while_the_body_is_read_is_refused() -> None:
    service, clock, token = await _setup()

    async def slow_body() -> bytes:
        clock.now += timedelta(seconds=61)
        return _BODY

    denial = await service.authorize(f"Bearer {token}", "POST", _PATH, slow_body)
    assert denial is not None
    assert denial.status == 401


async def test_token_revoked_while_the_body_is_read_is_refused() -> None:
    service, _, token = await _setup()

    async def body_then_revoke() -> bytes:
        await service.revoke(token)
        return _BODY

    denial = await service.authorize(f"Bearer {token}", "POST", _PATH, body_then_revoke)
    assert denial is not None
    assert denial.status == 401
