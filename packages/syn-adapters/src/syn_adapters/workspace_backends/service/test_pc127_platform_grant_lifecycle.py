"""A workspace's API token lives exactly as long as the workspace (PC-127, ADR-072).

Read at the consumer: the token handed to the workspace must authorize a read
through `PlatformTokenService.authorize` while the workspace is up, and must
stop authorizing once `create_workspace` has torn it down. A grant minted and
then dropped before `ManagedWorkspace`, or never revoked, fails here.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from syn_adapters.platform_access import InMemoryPlatformTokenStore, PlatformTokenService
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService

if TYPE_CHECKING:
    from collections.abc import Iterator

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

    async with service.create_workspace(execution_id="exec-pc127") as workspace:
        grant = workspace.platform_grant
        assert grant is not None
        assert grant.env["SYN_API_URL"] == "http://syn-platform.test"
        bearer = f"Bearer {grant.env['SYN_API_TOKEN']}"
        assert await tokens.authorize(bearer, "GET", "/executions") is None
        assert grant.token not in repr(workspace)

    denial = await tokens.authorize(bearer, "GET", "/executions")
    assert denial is not None
    assert denial.status == 401


@pytest.mark.asyncio
async def test_access_off_gives_the_workspace_nothing() -> None:
    tokens = PlatformTokenService(None, max_ttl_seconds=600)
    service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY, platform_tokens=tokens)

    async with service.create_workspace(execution_id="exec-pc127") as workspace:
        assert workspace.platform_grant is None
