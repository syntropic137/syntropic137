"""NoStreamEventStreamAdapter - explicit "streaming unsupported" for interactive-tmux.

Interactive-tmux workspaces are driven through the tmux pane API
(`send_message` / `await_completion` / `capture_response`, reached via
`InteractiveTmuxIsolationAdapter.provider_handle()`), not the `claude -p`
stream-json path that `workspace.stream()` implements for the Docker
backend. Before this adapter existed, `_create_interactive_tmux_impl`
wired a bare, un-configured `AgenticEventStreamAdapter()` (never given a
provider via `set_provider()`), so any call to `stream()` on an
interactive-tmux workspace raised the accidental, confusing
`RuntimeError("Provider not set. Call set_provider first.")` - a message
that describes an implementation detail rather than the actual
constraint (issue #771 item 5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )


class InteractiveTmuxStreamingUnsupportedError(RuntimeError):
    """Raised when `.stream()` is called against an interactive-tmux workspace.

    Interactive-tmux workspaces do not support the `claude -p` stream-json
    execution path. Callers should feature-detect
    (`hasattr(isolation_adapter, "provider_handle")`) and drive the agent
    through `provider_handle()`'s `send_message` / `await_completion` /
    `capture_response` API instead.
    """


class NoStreamEventStreamAdapter:
    """EventStreamPort implementation for backends that do not support streaming.

    Satisfies the `EventStreamPort` protocol's shape so it can be wired
    anywhere an `EventStreamPort` is expected, but every `stream()` call
    fails immediately and explicitly with
    `InteractiveTmuxStreamingUnsupportedError` rather than an accidental,
    unrelated error surfacing from an unconfigured provider.
    """

    @property
    def last_exit_code(self) -> int | None:
        """Always None - no stream has ever run on this backend."""
        return None

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Raise immediately; interactive-tmux does not support streaming."""
        del command, timeout_seconds, working_directory, environment
        msg = (
            f"interactive-tmux workspace {handle.isolation_id!r} does not "
            "support claude -p stream-json execution. Use "
            "provider_handle() and the send_message/await_completion/"
            "capture_response pane API instead."
        )
        raise InteractiveTmuxStreamingUnsupportedError(msg)
        yield ""  # pragma: no cover - unreachable; satisfies AsyncIterator typing


__all__ = ["InteractiveTmuxStreamingUnsupportedError", "NoStreamEventStreamAdapter"]
