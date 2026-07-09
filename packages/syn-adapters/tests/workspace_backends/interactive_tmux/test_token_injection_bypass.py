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

import syn_adapters.workspace_backends.interactive_tmux as interactive_tmux_pkg
from syn_adapters.workspace_backends.errors import WorkspaceProvisionError
from syn_adapters.workspace_backends.interactive_tmux import (
    NoopSidecarAdapter,
    NoopTokenInjectionAdapter,
    NoStreamEventStreamAdapter,
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
    # issue #771 item 5: interactive-tmux does not emit stream-json, so the
    # factory must wire the explicit "streaming unsupported" adapter rather
    # than a bare, un-configured AgenticEventStreamAdapter (which raised a
    # confusing "Provider not set" error if stream() was ever called).
    assert isinstance(service._event_stream, NoStreamEventStreamAdapter)


@pytest.mark.asyncio
async def test_interactive_event_stream_rejects_stream_calls() -> None:
    """The wired event-stream adapter fails loudly and explicitly on stream().

    Regression guard for issue #771 item 5: previously
    `_create_interactive_tmux_impl` wired `AgenticEventStreamAdapter()`
    without `set_provider()`, so any `stream()` call raised
    `RuntimeError("Provider not set. Call set_provider first.")` - a message
    describing an implementation detail rather than the real constraint.
    """
    from syn_adapters.workspace_backends.interactive_tmux import (
        InteractiveTmuxStreamingUnsupportedError,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

    with (
        patch.dict(os.environ, {"SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED": "true"}),
        patch.object(adapter_mod, "_InteractiveTmuxProvider", MagicMock()),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", True),
    ):
        service = WorkspaceService.create(config=_interactive_cfg())

    handle = IsolationHandle(
        isolation_id="itws-x",
        isolation_type="interactive-tmux",
        proxy_url=None,
        workspace_path="/workspace",
        host_workspace_path="",
    )
    with pytest.raises(InteractiveTmuxStreamingUnsupportedError, match="interactive-tmux"):
        async for _ in service._event_stream.stream(handle, ["claude", "-p", "hi"]):
            pass


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
    """Without the feature flag the factory MUST refuse — no silent fallback.

    Also asserts the typed error (issue #771 item 7): a bare RuntimeError
    gives error-mapping layers (`_fail_execution`, `syn execution show`)
    nothing to match against.
    """
    with (
        patch.dict(os.environ, {"SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED": "false"}),
        pytest.raises(WorkspaceProvisionError) as exc,
    ):
        WorkspaceService.create(config=_interactive_cfg())
    assert "SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED" in str(exc.value)


def test_provider_unavailable_raises_when_flag_on_but_import_missing() -> None:
    """If the submodule pin lacks the provider, the factory must say so.

    Patches both `adapter_mod.INTERACTIVE_TMUX_AVAILABLE` and the
    re-exported package-level name: `_create_interactive_tmux_impl` reads
    the latter (`from syn_adapters.workspace_backends.interactive_tmux
    import INTERACTIVE_TMUX_AVAILABLE`), which is a separate binding
    captured when the package's `__init__` ran — patching only the
    submodule attribute leaves that binding untouched.
    """
    with (
        patch.dict(os.environ, {"SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED": "true"}),
        patch.object(adapter_mod, "INTERACTIVE_TMUX_AVAILABLE", False),
        patch.object(interactive_tmux_pkg, "INTERACTIVE_TMUX_AVAILABLE", False),
        patch.object(adapter_mod, "_InteractiveTmuxProvider", None),
        pytest.raises(WorkspaceProvisionError) as exc,
    ):
        WorkspaceService.create(config=_interactive_cfg())
    assert "agentic_isolation" in str(exc.value)
    assert "agentprims-lab" in str(exc.value)
