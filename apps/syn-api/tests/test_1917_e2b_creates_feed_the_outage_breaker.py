"""The E2B executor's workspace service reports its creates to the Outage Breaker (#1917).

Tested at the consumer, ``build_workspace_service``: the sandbox client it
hands the E2B backend, not the breaker alone.
"""

from __future__ import annotations

import pytest
from agentic_isolation.providers import e2b_client

from syn_adapters.workspace_backends.e2b.breaker_client import BreakerE2BClient
from syn_adapters.workspace_backends.e2b.test_e2b_backend import SandboxDouble
from syn_adapters.workspace_backends.service import WorkspaceService, WorkspaceServiceConfig
from syn_shared.settings import reset_settings

pytestmark = pytest.mark.unit


def _client_built(monkeypatch: pytest.MonkeyPatch, *, run_queue: bool) -> object:
    from syn_api import _wiring

    handed: list[object] = []

    def record(_cls: type[WorkspaceService], *, e2b_client: object = None, **_: object) -> None:
        handed.append(e2b_client)

    monkeypatch.setattr(WorkspaceService, "create", classmethod(record))
    monkeypatch.setattr(_wiring, "get_platform_token_service", lambda: None)
    monkeypatch.setattr(e2b_client, "SdkE2BClient", lambda **_: SandboxDouble())
    monkeypatch.setenv("SYN_E2B_ENABLED", "true")
    monkeypatch.setenv("SYN_E2B_API_KEY", "e2b-invented-for-test")
    monkeypatch.setenv("SYN_E2B_TEMPLATE", "syn-template-under-test")
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true" if run_queue else "false")
    reset_settings()
    try:
        _wiring.build_workspace_service(WorkspaceServiceConfig(), None)
    finally:
        reset_settings()
    (client,) = handed
    return client


def test_with_the_run_queue_on_e2b_creates_go_through_the_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(_client_built(monkeypatch, run_queue=True), BreakerE2BClient)


def test_with_the_run_queue_off_there_is_no_row_to_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _client_built(monkeypatch, run_queue=False) is None
