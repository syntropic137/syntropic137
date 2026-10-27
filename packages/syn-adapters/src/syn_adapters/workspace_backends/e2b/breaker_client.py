"""The E2B sandbox client with its creates reported to the Outage Breaker (#1917).

Every operation is the wrapped client's, unchanged. Only ``create`` is
observed: a sandbox that could not be created is the outage signal (research
"Failure modes": creates fail while the heartbeat continues). Any exception
counts, an outage, a refused quota or a bad template alike: each would fail
every run this executor claimed. The create's own error is re-raised as it was.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentic_isolation.providers.e2b_client import (
        E2BSandboxClient,
        SandboxCommand,
        SandboxListing,
    )
    from pydantic import SecretStr

    from syn_adapters.execution_host.outage_breaker import OutageBreaker
    from syn_adapters.workspace_backends.e2b.listing import SandboxListings


class BreakerE2BClient:
    """An ``E2BSandboxClient`` whose ``create`` outcomes feed an ``OutageBreaker``."""

    def __init__(self, client: E2BSandboxClient, breaker: OutageBreaker) -> None:
        self._client = client
        self._breaker = breaker

    async def create(
        self, *, template: str, metadata: Mapping[str, str], lifetime_seconds: int
    ) -> str:
        try:
            sandbox_id = await self._client.create(
                template=template, metadata=metadata, lifetime_seconds=lifetime_seconds
            )
        except Exception:
            await self._breaker.failed()
            raise
        await self._breaker.succeeded()
        return sandbox_id

    async def list(self, metadata: Mapping[str, str]) -> SandboxListings:
        return await self._client.list(metadata)

    async def lookup(self, sandbox_id: str) -> SandboxListing | None:
        return await self._client.lookup(sandbox_id)

    async def kill(self, sandbox_id: str) -> bool:
        return await self._client.kill(sandbox_id)

    async def pause(self, sandbox_id: str) -> None:
        await self._client.pause(sandbox_id)

    async def start(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None,
        env: Mapping[str, str],
        timeout: float | None,
        user: str,
        stdin: bytes | None = None,
    ) -> SandboxCommand:
        return await self._client.start(
            sandbox_id, command, cwd=cwd, env=env, timeout=timeout, user=user, stdin=stdin
        )

    async def reconnect(self, sandbox_id: str, pid: int) -> SandboxCommand:
        return await self._client.reconnect(sandbox_id, pid)

    async def read_bytes(self, sandbox_id: str, path: str, *, user: str) -> bytes:
        return await self._client.read_bytes(sandbox_id, path, user=user)

    async def write_bytes(self, sandbox_id: str, path: str, content: bytes, *, user: str) -> None:
        await self._client.write_bytes(sandbox_id, path, content, user=user)


def sdk_client_with_breaker(api_key: SecretStr, breaker: OutageBreaker) -> BreakerE2BClient:
    """The e2b SDK client for ``api_key``, its creates feeding ``breaker``."""
    from agentic_isolation.providers.e2b_client import SdkE2BClient

    return BreakerE2BClient(SdkE2BClient(api_key=api_key.get_secret_value()), breaker)
