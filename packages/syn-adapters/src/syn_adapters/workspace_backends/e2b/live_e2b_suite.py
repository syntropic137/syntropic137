"""The E2B conformance suite against REAL E2B (#1915). Never runs in CI.

Not named ``test_*.py`` on purpose: no default or CI collection picks it up,
so it is excluded from CI rather than collected there and skipped. pytest
collects it only when named, which ``just test-e2b`` does. Marker ``e2b``,
also deselected by default, as a second guard. Without
SYN_E2B_API_KEY and SYN_E2B_TEMPLATE each test SKIPS with that reason; a skip
is not a pass. Nothing here has been run yet: no E2B key existed when it was
written. Run it locally with ``just test-e2b`` (docs/deployment/e2b.md).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from agentic_isolation import E2BWorkspaceProvider
from agentic_isolation.providers.e2b_client import SdkE2BClient

from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter
from syn_adapters.workspace_backends.backend_kit import BackendKit
from syn_adapters.workspace_backends.e2b import e2b_conformance as suite
from syn_adapters.workspace_backends.errors import WorkspaceTeardownError

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.e2b


def _required() -> tuple[str, str]:
    missing = [n for n in ("SYN_E2B_API_KEY", "SYN_E2B_TEMPLATE") if not os.environ.get(n)]
    if missing:
        pytest.skip(f"NOT RUN: real E2B needs {' and '.join(missing)} (see docs/deployment/e2b.md)")
    return os.environ["SYN_E2B_API_KEY"], os.environ["SYN_E2B_TEMPLATE"]


class _NoopKill:
    """The real SDK client with a kill that claims success and does nothing."""

    def __init__(self, client: SdkE2BClient) -> None:
        self._client = client

    def __getattr__(self, name: str) -> object:
        return getattr(self._client, name)

    async def kill(self, sandbox_id: str) -> bool:
        return True


def _adapter(template: str, client: object) -> tuple[AgenticIsolationAdapter, E2BWorkspaceProvider]:
    provider = E2BWorkspaceProvider(template, client=client)  # type: ignore[arg-type]
    kit = BackendKit.e2b(
        template,
        cpu_count=int(os.environ.get("SYN_E2B_CPU_COUNT", "2")),
        memory_mb=int(os.environ.get("SYN_E2B_MEMORY_MB", "2048")),
    )
    return AgenticIsolationAdapter(kit=kit, provider=provider), provider


@pytest.fixture
def live_client() -> Iterator[tuple[SdkE2BClient, str]]:
    key, template = _required()
    yield SdkE2BClient(api_key=key), template


async def test_conformance_against_real_e2b(live_client: tuple[SdkE2BClient, str]) -> None:
    client, template = live_client
    adapter, provider = _adapter(template, client)
    config = suite.isolation_config(template)
    labels = suite.run_labels(config)
    handle = await suite.check_create(adapter, config)
    try:
        await suite.check_merged_stream_and_outcome(adapter, handle)
        await suite.check_binary_round_trip(adapter, handle)
        await suite.check_list_and_attach(provider, handle, labels)
    finally:
        await suite.check_cleanup(adapter, provider, handle, labels)


async def test_negative_control_noop_kill_fails_cleanup_against_real_e2b(
    live_client: tuple[SdkE2BClient, str],
) -> None:
    client, template = live_client
    adapter, provider = _adapter(template, _NoopKill(client))
    config = suite.isolation_config(template)
    handle = await suite.check_create(adapter, config)
    try:
        with pytest.raises(WorkspaceTeardownError):
            await suite.check_cleanup(adapter, provider, handle, suite.run_labels(config))
        assert await client.lookup(handle.isolation_id) is not None
    finally:
        # Free the sandbox the broken kill left behind, through the real kill.
        _, real = _adapter(template, client)
        await real.teardown(await real.attach(handle.isolation_id, expect_labels={}))
