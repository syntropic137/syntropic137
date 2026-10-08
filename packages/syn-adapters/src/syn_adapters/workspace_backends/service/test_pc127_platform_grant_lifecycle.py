"""A workspace's API token lives exactly as long as the workspace (PC-127, ADR-072).

Read at the consumer: the environment the agent is LAUNCHED with (what the
event-stream port receives from `ManagedWorkspace.stream`) must carry a token
that authorizes a read while the workspace is up, and stops authorizing once
`create_workspace` has torn it down. A grant minted and dropped before the
launch, or never revoked, fails here.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from syn_adapters.platform_access import InMemoryPlatformTokenStore, PlatformTokenService
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_shared.env_constants import ENV_SYN_PHASE_DEADLINE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _test_env() -> Iterator[None]:
    with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
        yield


@pytest.mark.asyncio
async def test_grant_is_usable_during_the_phase_and_revoked_after() -> None:
    tokens = PlatformTokenService(
        InMemoryPlatformTokenStore(),
        max_ttl_seconds=600,
        workspace_api_url="http://syn-platform.test",
    )
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY, platform_tokens=tokens)

    launched: list[dict[str, str]] = []

    async def capturing_stream(
        handle: object, command: list[str], **kwargs: object
    ) -> AsyncIterator[str]:
        environment = kwargs["environment"]
        assert isinstance(environment, dict)
        launched.append(environment)
        yield "{}"

    service._event_stream.stream = capturing_stream  # type: ignore[method-assign]

    async with service.create_workspace(execution_id="exec-pc127") as workspace:
        async for _ in workspace.stream(["claude"], environment={"CLAUDE_SESSION_ID": "s-1"}):
            pass
        (env,) = launched
        assert env["CLAUDE_SESSION_ID"] == "s-1"  # the caller's env survives the merge
        assert env["SYN_API_URL"] == "http://syn-platform.test"
        bearer = f"Bearer {env['SYN_API_TOKEN']}"
        assert await tokens.authorize(bearer, "GET", "/executions") is None
        assert env["SYN_API_TOKEN"] not in repr(workspace)

    denial = await tokens.authorize(bearer, "GET", "/executions")
    assert denial is not None
    assert denial.status == 401


@pytest.mark.asyncio
async def test_access_off_gives_the_workspace_nothing() -> None:
    tokens = PlatformTokenService(None, max_ttl_seconds=600)
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY, platform_tokens=tokens)

    async with service.create_workspace(execution_id="exec-pc127") as workspace:
        assert workspace.platform_grant is None


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.mark.asyncio
async def test_grant_dies_at_the_phase_deadline_even_when_revocation_fails() -> None:
    clock = _Clock()
    tokens = PlatformTokenService(InMemoryPlatformTokenStore(), max_ttl_seconds=3600, now=clock)
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY, platform_tokens=tokens)
    launched: list[dict[str, str]] = []

    async def capturing_stream(
        handle: object, command: list[str], **kwargs: object
    ) -> AsyncIterator[str]:
        environment = kwargs["environment"]
        assert isinstance(environment, dict)
        launched.append(environment)
        yield "{}"

    service._event_stream.stream = capturing_stream  # type: ignore[method-assign]
    # The deadline the domain produces (`_phase_deadline_environment`): one
    # 60s phase, shared by every attempt in it.
    deadline = clock.now + timedelta(seconds=60)
    phase_env = {ENV_SYN_PHASE_DEADLINE: deadline.isoformat(timespec="seconds")}

    async def unreachable(token: str) -> None:
        raise ConnectionError("redis down")

    tokens.revoke = unreachable  # type: ignore[method-assign]
    async with service.create_workspace(execution_id="exec-pc127") as workspace:
        for _attempt in range(2):  # a retry must not extend the grant
            async for _ in workspace.stream(["claude"], environment=dict(phase_env)):
                pass
            clock.now += timedelta(seconds=20)
        bearer = f"Bearer {launched[0]['SYN_API_TOKEN']}"
        assert await tokens.authorize(bearer, "GET", "/executions") is None

    clock.now = deadline - timedelta(seconds=1)
    assert await tokens.authorize(bearer, "GET", "/executions") is None
    clock.now = deadline + timedelta(seconds=1)
    denial = await tokens.authorize(bearer, "GET", "/executions")
    assert denial is not None
    assert denial.status == 401


@pytest.mark.asyncio
async def test_a_later_deadline_never_extends_a_grant() -> None:
    clock = _Clock()
    tokens = PlatformTokenService(InMemoryPlatformTokenStore(), max_ttl_seconds=60, now=clock)
    token = await tokens.issue("exec-pc127")
    await tokens.bound_to_deadline(token, clock.now + timedelta(hours=2))
    clock.now += timedelta(seconds=61)
    assert await tokens.authorize(f"Bearer {token}", "GET", "/executions") is not None
