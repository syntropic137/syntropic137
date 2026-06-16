"""Interactive-tmux workspace backend.

Phase C2 (smallest viable seam): exposes the InteractiveTmuxIsolationAdapter
that wraps `agentic_isolation.providers.interactive_tmux.InteractiveTmuxProvider`
(shipped from agentic-primitives, branch `agentprims-lab`, EXP-05).

This is a sibling to `syn_adapters.workspace_backends.agentic` — same shape
(`is_available`, `create`, `destroy`, `execute`, `copy_to`, `copy_from`,
`health_check`), different underlying provider. It is OFF by default
behind `SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED`; see
`docs/plans/interactive-tmux-integration.md` for the rollout plan.
"""

from syn_adapters.workspace_backends.interactive_tmux.adapter import (
    INTERACTIVE_TMUX_AVAILABLE,
    InteractiveTmuxIsolationAdapter,
    InteractiveTmuxUnavailableError,
)
from syn_adapters.workspace_backends.interactive_tmux.noop_sidecar import (
    NoopSidecarAdapter,
)
from syn_adapters.workspace_backends.interactive_tmux.noop_token_injection import (
    NoopTokenInjectionAdapter,
)

__all__ = [
    "INTERACTIVE_TMUX_AVAILABLE",
    "InteractiveTmuxIsolationAdapter",
    "InteractiveTmuxUnavailableError",
    "NoopSidecarAdapter",
    "NoopTokenInjectionAdapter",
]
