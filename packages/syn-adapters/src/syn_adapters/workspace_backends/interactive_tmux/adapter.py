"""InteractiveTmuxIsolationAdapter — wraps the EXP-05 interactive-tmux provider.

Mirrors `AgenticIsolationAdapter` (in `syn_adapters.workspace_backends.agentic`)
but delegates container lifecycle and command execution to
`agentic_isolation.providers.interactive_tmux.InteractiveTmuxProvider`.

This adapter is off by default. It is selected by
`WorkspaceServiceConfig(provider_kind="interactive-tmux")` together with
the `SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED=true` feature flag (see
`syn_shared.settings.workspace.WorkspaceSettings`). The default
`claude -p` Docker path is untouched when the flag is off.

The richer prompt round-trip API (send_message / await_completion /
capture_response) lives on the underlying driver workspace and is reached
via the `provider_handle()` accessor — kept off the ports protocol because
it is interactive-tmux-specific. The default Docker adapter returns None.

See:
- docs/plans/interactive-tmux-integration.md
- lib/agentic-primitives/providers/workspaces/interactive-tmux/README.md
- lib/agentic-primitives/lib/python/agentic_isolation/agentic_isolation/providers/interactive_tmux/__init__.py
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
from typing import TYPE_CHECKING, Any, TypeVar

from syn_adapters.workspace_backends.agentic.adapter_copy import (
    check_workspace_health,
    copy_files_from_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
        IsolationConfig,
        IsolationHandle,
    )

_T = TypeVar("_T")

logger = logging.getLogger(__name__)


class InteractiveTmuxUnavailableError(RuntimeError):
    """Raised when the interactive-tmux provider cannot be loaded.

    Reasons (most → least likely):
      * Docker is not installed on the host (the driver shells out to it).
      * The agentic-primitives submodule is pinned at a commit that does
        not ship `agentic_isolation.providers.interactive_tmux` (i.e.,
        not on `agentprims-lab` or its successor).
      * The host has no `~/.claude/` / `~/.claude.json` (EXP-05a finding:
        both are required for the Claude CLI to start authenticated).
    """


def _try_import_provider() -> tuple[Any, str | None]:
    """Locate the InteractiveTmuxProvider class.

    Returns (provider_class_or_None, error_message_or_None). Kept as a
    function (not an import-time statement) so that import-time failures
    in environments that do not have the agentprims-lab submodule pin do
    not crash module loading — the flag-gated wiring path can still
    short-circuit with a clean error.
    """
    try:
        from agentic_isolation.providers.interactive_tmux import (  # type: ignore[import-not-found]
            InteractiveTmuxProvider,
        )
    except ImportError as exc:
        return None, str(exc)
    return InteractiveTmuxProvider, None


_InteractiveTmuxProvider, _IMPORT_ERROR = _try_import_provider()

INTERACTIVE_TMUX_AVAILABLE: bool = _InteractiveTmuxProvider is not None
"""True when `agentic_isolation.providers.interactive_tmux` was importable
at adapter-module load time. False when the agentic-primitives submodule
is pinned at a commit that does not include the provider."""


class InteractiveTmuxIsolationAdapter:
    """Isolation backend port implementation for the interactive-tmux provider.

    Constructor mirrors `AgenticIsolationAdapter` but takes only the bits
    that this provider honours today. The agentic_isolation provider does
    its own bind-mount layout (claude/codex/gemini auth dirs) and runs a
    fixed `sleep infinity` entrypoint — most of WorkspaceConfig is ignored
    by the underlying driver; we forward what is honoured and document the
    rest in the plan doc.
    """

    def __init__(
        self,
        *,
        default_image: str | None = None,
        startup_timeout_s: float = 45.0,
        strict_startup: bool = True,
    ) -> None:
        if _InteractiveTmuxProvider is None:
            detail = _IMPORT_ERROR or "InteractiveTmuxProvider missing"
            msg = (
                "interactive-tmux workspace backend requested but "
                "agentic_isolation.providers.interactive_tmux is not "
                f"importable ({detail}). Pin the agentic-primitives "
                "submodule at a commit on `agentprims-lab` (or its "
                "successor) and re-install."
            )
            raise InteractiveTmuxUnavailableError(msg)

        self._default_image = default_image
        self._provider = _InteractiveTmuxProvider(
            default_image=default_image,
            startup_timeout_s=startup_timeout_s,
            strict_startup=strict_startup,
        )
        self._workspaces: dict[str, Any] = {}
        # Dedicated event loop (in a background thread) that runs every
        # provider coroutine. The provider owns an `asyncio.Lock`, which is
        # loop-affine: it binds to the first loop that acquires it and
        # raises RuntimeError from any other loop. Driving each call on a
        # fresh `asyncio.run` loop would therefore crash on the second
        # provider call - including the ordinary create() -> destroy()
        # sequence, since create() binds the lock to a loop that is closed
        # by the time destroy() runs. One stable loop keeps the lock valid
        # across the whole workspace lifetime and keeps the blocking driver
        # work off the caller's loop. Lazily started on first use.
        self._provider_loop_obj: asyncio.AbstractEventLoop | None = None
        self._provider_loop_thread: threading.Thread | None = None

    def _provider_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._provider_loop_obj
        if loop is not None and not loop.is_closed():
            return loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever,
            name=f"itmux-provider-{id(self):x}",
            daemon=True,
        )
        thread.start()
        self._provider_loop_obj = loop
        self._provider_loop_thread = thread
        return loop

    async def _call_provider(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Run a provider coroutine on the dedicated loop, awaited from ours.

        `run_coroutine_threadsafe` schedules `coro` on the provider loop and
        returns a concurrent future; `wrap_future` lets us await it on the
        caller's loop without blocking it.
        """
        loop = self._provider_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return await asyncio.wrap_future(future)

    def _shutdown_provider_loop(self) -> None:
        """Stop the dedicated loop once no workspaces remain on this adapter."""
        loop = self._provider_loop_obj
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread = self._provider_loop_thread
        if thread is not None:
            thread.join(timeout=5.0)
        loop.close()
        self._provider_loop_obj = None
        self._provider_loop_thread = None

    @staticmethod
    def is_available() -> bool:
        """Check Docker is on PATH and the provider class was importable."""
        return INTERACTIVE_TMUX_AVAILABLE and shutil.which("docker") is not None

    async def create(self, config: IsolationConfig) -> IsolationHandle:
        """Create an interactive-tmux workspace from a Syn137 isolation config."""
        from agentic_isolation import WorkspaceConfig  # type: ignore[import-not-found]

        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationHandle,
        )

        ws_config = WorkspaceConfig(
            provider="interactive-tmux",
            image=config.image or self._default_image or "",
            working_dir="/workspace",
            environment=dict(config.environment) if config.environment else {},
            labels={
                "syn.execution_id": config.execution_id,
                "syn.workspace_id": config.workspace_id,
            },
        )

        # The provider's create() is async-def but blocking internally
        # (subprocess + sleep loops up to startup_timeout_s, ~45s by
        # default). Running it on the dedicated provider loop keeps that
        # blocking window off this adapter's event loop while satisfying
        # the provider lock's loop affinity (see `_call_provider`).
        workspace_obj = await self._call_provider(self._provider.create(ws_config))
        self._workspaces[workspace_obj.id] = workspace_obj

        logger.info(
            "Created interactive-tmux workspace (id=%s, execution=%s, agents=%s)",
            workspace_obj.id,
            config.execution_id,
            workspace_obj.metadata.get("enabled_agents"),
        )

        return IsolationHandle(
            isolation_id=workspace_obj.id,
            isolation_type="interactive-tmux",
            proxy_url=None,
            workspace_path="/workspace",
            host_workspace_path=workspace_obj.metadata.get("workspace_dir", ""),
        )

    async def destroy(self, handle: IsolationHandle) -> None:
        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            logger.warning("Interactive-tmux workspace not found: %s", handle.isolation_id)
            return
        logger.info("Destroying interactive-tmux workspace (id=%s)", handle.isolation_id)
        # Same blocking-in-async concern as create() (~2s of docker rm /
        # stop() calls this time): run on the dedicated provider loop so
        # this event loop isn't held up for the duration.
        # Pop only AFTER a successful provider destroy. If destroy raises
        # (e.g. docker timeout), the handle stays in _workspaces so the
        # caller can retry instead of leaking the tmux/Docker resources.
        await self._call_provider(self._provider.destroy(workspace))
        self._workspaces.pop(handle.isolation_id, None)
        # Once the adapter holds no workspaces, the dedicated provider loop
        # has nothing left to serve; stop it so a long-lived syn-api process
        # does not accumulate idle loop threads across executions.
        if not self._workspaces:
            self._shutdown_provider_loop()

    async def execute(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute a command inside the interactive-tmux container via docker exec.

        Note: this does NOT go through the agent panes; it is the same
        plain `docker exec` shape that ManagedWorkspace.run_setup_phase
        relies on. Prompt round-trips go via `provider_handle()` instead.
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            ExecutionResult,
        )

        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=0.0,
                stderr="Workspace not found",
            )

        cmd_str = " ".join(command)
        result = await self._call_provider(
            self._provider.execute(
                workspace,
                cmd_str,
                timeout=float(timeout_seconds) if timeout_seconds else None,
                cwd=working_directory,
                env=environment,
            )
        )

        return ExecutionResult(
            exit_code=result.exit_code,
            success=result.success,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
        )

    async def health_check(self, handle: IsolationHandle) -> bool:
        return check_workspace_health(self._workspaces, handle)

    async def copy_to(
        self,
        handle: IsolationHandle,
        files: list[tuple[str, bytes]],
        base_path: str = "/workspace",
    ) -> None:
        """Write files to the workspace via the provider's write_file API.

        Slower than the agentic adapter's bind-mount copy, but simpler and
        works without knowing the host workspace path. Acceptable for v1.
        """
        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            raise FileNotFoundError(f"Interactive-tmux workspace not found: {handle.isolation_id}")
        for relative_path, content in files:
            full_path = f"{base_path.rstrip('/')}/{relative_path}" if relative_path else base_path
            await self._call_provider(self._provider.write_file(workspace, full_path, content))

    async def copy_from(
        self,
        handle: IsolationHandle,
        patterns: list[str],
        base_path: str = "/workspace",
    ) -> list[tuple[str, bytes]]:
        """Best-effort copy_from via the bind-mounted host workspace dir."""
        return await copy_files_from_workspace(handle, patterns, base_path)

    def provider_handle(self, handle: IsolationHandle) -> Any | None:  # noqa: ANN401  # driver type lives in agentic-primitives, intentionally loose at this seam
        """Return the underlying InteractiveTmuxWorkspace driver handle.

        Interactive-tmux-specific entry point for the rich prompt API
        (`send_message` / `await_completion` / `capture_response`). The
        default Docker isolation adapter does not implement this method
        (workflow code feature-detects with `hasattr`).

        The return type is intentionally `Any` because the concrete class
        lives in the agentic-primitives submodule (driver
        `interactive_tmux.InteractiveTmuxWorkspace`) and importing it
        here at type-check time would couple this module to the
        submodule layout. Callers should treat the value as opaque and
        speak to it through the documented `send_message` /
        `await_completion` / `capture_response` / `stop` surface.
        """
        workspace = self._workspaces.get(handle.isolation_id)
        if workspace is None:
            return None
        return getattr(workspace, "_handle", None)
