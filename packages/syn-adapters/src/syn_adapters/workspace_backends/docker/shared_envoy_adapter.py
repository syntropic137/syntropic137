"""Shared Envoy proxy adapter — implements SidecarPort for shared proxy (ISS-43).

Instead of spinning up a per-workspace sidecar container, this adapter points all
workspaces at a single shared Envoy proxy service (``syn-envoy-proxy``). The proxy
injects credentials into outbound requests; agent containers never see API keys.

Phase 1 (this PR):
    - Single shared key loaded from env vars on the proxy container.
    - ``start()`` returns a handle pointing to the shared proxy (no container created).
    - ``stop()`` is a no-op (proxy is always running).
    - ``configure_tokens()`` is a no-op (single shared key, no per-execution tokens).

Phase 2 (future):
    - Per-execution credentials registered in Redis.
    - ``configure_tokens()`` writes scoped credentials with TTL.
    - ``stop()`` revokes per-execution credentials.

See ADR-022: Secure Token Architecture.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        SidecarConfig,
        SidecarHandle,
        TokenType,
    )

logger = logging.getLogger(__name__)

DEFAULT_PROXY_URL = "http://syn-envoy-proxy:8081"


class SharedEnvoyAdapter:
    """SidecarPort implementation backed by a shared Envoy proxy.

    The shared proxy is deployed as an always-on Docker Compose service
    (``envoy-proxy``) that bridges the internal agent network and the
    external network. Agent containers on the internal network route
    all HTTP traffic through this proxy.

    Usage:
        adapter = SharedEnvoyAdapter(proxy_url="http://syn-envoy-proxy:8081")
        handle = await adapter.start(config, isolation_handle)
        # handle.proxy_url == "http://syn-envoy-proxy:8081"
        await adapter.stop(handle)  # no-op for shared proxy
    """

    def __init__(self, proxy_url: str = DEFAULT_PROXY_URL) -> None:
        self._proxy_url = proxy_url

    async def start(
        self,
        config: SidecarConfig,  # noqa: ARG002
        isolation_handle: IsolationHandle,  # noqa: ARG002
    ) -> SidecarHandle:
        """Return a handle pointing to the shared Envoy proxy.

        No container is created — the proxy is always running.
        """
        from datetime import UTC, datetime

        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            SidecarHandle,
        )

        logger.info("Using shared Envoy proxy at %s", self._proxy_url)

        return SidecarHandle(
            sidecar_id="shared-envoy-proxy",
            proxy_url=self._proxy_url,
            started_at=datetime.now(UTC),
        )

    async def stop(self, handle: SidecarHandle) -> None:
        """No-op for shared proxy — it is always running.

        Phase 2: Will revoke per-execution credentials from Redis.
        """
        logger.debug(
            "stop() called for shared proxy (no-op, sidecar_id=%s)",
            handle.sidecar_id,
        )

    async def configure_tokens(
        self,
        handle: SidecarHandle,
        tokens: dict[TokenType, str],
        ttl_seconds: int,
    ) -> None:
        """No-op for Phase 1 — single shared key loaded from proxy env vars.

        Phase 2: Will register per-execution credentials in Redis with TTL.
        """

    async def health_check(self, handle: SidecarHandle) -> bool:  # noqa: ARG002
        """Check Envoy admin /ready endpoint."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl",
                "-sf",
                f"{self._proxy_url.replace(':8081', ':9901')}/ready",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return proc.returncode == 0 and b"LIVE" in stdout
        except Exception:
            logger.warning("Shared Envoy health check failed")
            return False
