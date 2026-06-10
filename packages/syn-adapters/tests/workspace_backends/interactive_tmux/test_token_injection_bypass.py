"""Envoy ext_authz bypass regression test (orchestrator review, 2026-06-10).

The interactive-tmux path authenticates outbound calls to api.anthropic.com
via OAuth mounted from the host (~/.claude/.credentials.json). Syn137's
default SidecarTokenInjectionAdapter separately wires Envoy ext_authz to
inject ANTHROPIC_API_KEY. Doing BOTH would put two identities on the wire
(OAuth Max plan + API-key account) — a correctness and credential-confusion
risk.

This test asserts the interactive-tmux factory does NOT wire
SidecarTokenInjectionAdapter (or any vending adapter) — it wires the
NoopTokenInjectionAdapter/NoopSidecarAdapter that this PR added for
exactly this purpose.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from syn_adapters.workspace_backends.interactive_tmux import (
    NoopSidecarAdapter,
    NoopTokenInjectionAdapter,
)
from syn_adapters.workspace_backends.interactive_tmux import adapter as adapter_mod
from syn_adapters.workspace_backends.service import (
    WorkspaceService,
    WorkspaceServiceConfig,
)


def _interactive_cfg() -> WorkspaceServiceConfig:
    return WorkspaceServiceConfig(provider_kind="interactive-tmux")


def test_interactive_factory_uses_noop_token_injection() -> None:
    """When provider_kind='interactive-tmux', the service MUST wire the no-op
    token-injection adapter — NOT SidecarTokenInjectionAdapter."""
    with (
        patch.dict(os.environ, {"SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED": "true"}),
        patch.object(adapter_mod, "_InteractiveTmuxProvider", MagicMock()),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        service = WorkspaceService.create(config=_interactive_cfg())

    assert isinstance(service._token_injection, NoopTokenInjectionAdapter)
    assert isinstance(service._sidecar, NoopSidecarAdapter)


@pytest.mark.asyncio
async def test_noop_token_injection_inject_yields_zero_tokens() -> None:
    """Belt-and-braces: the no-op adapter's inject() result has tokens_injected=()."""
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        TokenType,
    )

    adapter = NoopTokenInjectionAdapter()
    result = await adapter.inject(
        IsolationHandle(
            isolation_id="ws-x",
            isolation_type="interactive-tmux",
            proxy_url=None,
            workspace_path="/workspace",
            host_workspace_path="",
        ),
        execution_id="exec-x",
        token_types=[TokenType.ANTHROPIC, TokenType.GITHUB],
    )

    assert result.success is True
    assert result.tokens_injected == ()
    assert result.ttl_seconds is None


def test_flag_off_rejects_interactive_provider_kind() -> None:
    """Without the feature flag the factory MUST refuse — no silent fallback."""
    with (
        patch.dict(os.environ, {"SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED": "false"}),
        pytest.raises(RuntimeError) as exc,
    ):
        WorkspaceService.create(config=_interactive_cfg())
    assert "SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED" in str(exc.value)


def test_provider_unavailable_raises_when_flag_on_but_import_missing() -> None:
    """If the submodule pin lacks the provider, the factory must say so."""
    with (
        patch.dict(os.environ, {"SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED": "true"}),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", False),
        patch.object(adapter_mod, "_InteractiveTmuxProvider", None),
        pytest.raises(RuntimeError) as exc,
    ):
        WorkspaceService.create(config=_interactive_cfg())
    assert "agentic_isolation" in str(exc.value)
    assert "agentprims-lab" in str(exc.value)
