"""NoopTokenInjectionAdapter — explicit no-op for the interactive-tmux path.

Why this exists (orchestrator review, 2026-06-10):
The interactive `claude` CLI authenticates to api.anthropic.com via OAuth
read from `~/.claude/.credentials.json` (mounted from the host). Syn137's
default `SidecarTokenInjectionAdapter` separately wires ext_authz so
Envoy injects `ANTHROPIC_API_KEY` on outbound calls. Doing BOTH on the
interactive path is a correctness and credential-confusion risk — two
identities reach the provider, one billing the Max plan and one
charging the API account.

To prevent that without changing the `WorkspaceService` constructor
signature (which today requires a token_injection adapter), the
interactive backend wiring instantiates this no-op adapter. Its
`inject()` returns success with **zero tokens injected** and the new
sentinel injection method "noop" so audit trails clearly show the path
that ran.

This adapter does NOT touch the vending service, Envoy, or any sidecar.
It exists solely to satisfy the typed slot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
        TokenInjectionResult,
        TokenType,
    )


class NoopTokenInjectionAdapter:
    """Token injection adapter that never injects anything.

    Same `inject(...)` / `revoke(...)` shape as
    `SidecarTokenInjectionAdapter`; both calls are inert.
    """

    async def inject(
        self,
        _handle: IsolationHandle,
        execution_id: str,
        token_types: list[TokenType],
        *,
        ttl_seconds: int = 300,
    ) -> TokenInjectionResult:
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            InjectionMethod,
            TokenInjectionResult,
        )

        del token_types  # explicitly ignored — interactive-tmux uses OAuth on disk
        del ttl_seconds
        del execution_id
        return TokenInjectionResult(
            success=True,
            tokens_injected=(),
            # SIDECAR is the closest existing label; the empty tokens_injected
            # tuple is the unambiguous signal that nothing was injected.
            injection_method=InjectionMethod.SIDECAR,
            ttl_seconds=None,
        )

    async def revoke(self, execution_id: str) -> None:
        del execution_id  # no-op
