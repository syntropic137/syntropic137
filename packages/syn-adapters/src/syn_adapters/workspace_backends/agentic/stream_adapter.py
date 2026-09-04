"""Agentic event stream adapter - real-time stdout streaming for observability.

Separated from adapter.py for single-responsibility clarity.
See ADR-021: Isolated Workspace Architecture.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from syn_adapters.workspace_backends.agentic.stream_helpers import (
    _build_exec_command,
    _cleanup_process,
)
from syn_adapters.workspace_backends.agentic.stream_reader import (
    StreamOutcome,
    read_lines,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentic_isolation import (
        WorkspaceDockerProvider,
    )

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

logger = logging.getLogger(__name__)

#: GNU ``timeout``'s conventional status for "killed because the time limit
#: elapsed". NOT 128+SIGTERM, which would be 143. The local isolation provider
#: already uses 124 for the same meaning, and nothing in the execution path
#: interprets specific exit codes -- cancellation is driven by
#: ``interrupt_requested``, not by a status number -- so this cannot be
#: mistaken for a cancel.
_TIMEOUT_EXIT_CODE = 124


def _resolve_stream_exit_code(exit_code: int | None, *, timed_out: bool) -> int | None:
    """Return the status a truncated stream should report.

    Pure and module-level so the decision is testable without a container. The
    branch this replaces lived inline and, as a codex review pointed out, could
    be deleted with every test still green.

    A timed-out stream that the transport reported as success becomes
    ``_TIMEOUT_EXIT_CODE``. `docker exec` exits 0 when SIGTERM'd -- verified
    directly against a real container -- so success cannot be believed here.

    An already-failing status is left ALONE: it is more specific than "timed
    out" and the operator needs the real one. A stream that was not truncated is
    never rewritten, which is what keeps cancellation (driven by
    ``interrupt_requested``, not by a status) out of this path.
    """
    if timed_out and not exit_code:
        return _TIMEOUT_EXIT_CODE
    return exit_code


class AgenticEventStreamAdapter:
    """Implements EventStreamPort using agentic_isolation streaming.

    This adapter provides real-time stdout streaming for observability.
    """

    def __init__(self) -> None:
        """Initialize the adapter."""
        self._provider: WorkspaceDockerProvider | None = None
        self._last_exit_code: int | None = None

    @property
    def last_exit_code(self) -> int | None:
        """Exit code from the most recent stream() call.

        Returns None if no stream has completed yet.
        """
        return self._last_exit_code

    def set_provider(self, provider: WorkspaceDockerProvider) -> None:
        """Set the provider for streaming.

        Called by AgenticIsolationAdapter to share the provider.
        """
        self._provider = provider

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream stdout lines from command execution.

        Args:
            handle: Handle from isolation adapter
            command: Command to execute
            timeout_seconds: Max execution time
            working_directory: Working directory override
            environment: Additional environment variables
            wrapper_name: The ``$0`` the container-side wrapper announces
                itself under, from ``AgentLaunchEvidence.wrapper_name``. NOT
                passed through ``environment``: the agent inherits that, and a
                name the agent can read is a name it can forge (#1065). It
                reaches the container as wrapper argv instead, which ``exec``
                overwrites before there is an agent to look at it.

        Yields:
            Individual stdout lines as they are produced

        ARCHITECTURE NOTE — stderr=STDOUT is intentional (ADR-043):
        -----------------------------------------------------------------
        stderr=STDOUT merges any direct stderr from the claude CLI process into the
        stdout pipe so nothing is silently discarded (edge cases, internal errors).

        HOW GIT HOOK EVENTS ACTUALLY FLOW (important — not the obvious path):
        When Claude runs `git commit` via the Bash tool, the post-commit hook fires
        and emits JSONL to stderr. Claude Code captures Bash tool stderr as part of
        the tool output, then packages it inside a stream-json "user/tool_result"
        event. The JSONL arrives EMBEDDED inside tool_result content — NOT as a
        standalone raw line. WorkflowExecutionEngine scans each tool_result's full
        content string for embedded JSONL (see the tool_result branch in the loop).

        stderr=PIPE would silently discard any stderr escaping Claude Code's own
        packaging. Do not revert to PIPE or DEVNULL.

        IMPORTANT — TWO DOCKER EXEC PATHS EXIST. This file is the production path
        (used by the workspace service). agentic_isolation/providers/docker.py has
        the same fix but is only used in agentic_isolation contexts. Both must stay
        in sync — changing docker.py alone has no effect on the dashboard.
        """
        stream_timeout = float(timeout_seconds) if timeout_seconds else None
        if self._provider is None:
            raise RuntimeError("Provider not set. Call set_provider first.")

        container_name = f"agentic-ws-{handle.isolation_id.split('-')[1]}"
        exec_cmd = _build_exec_command(
            container_name,
            command,
            working_directory,
            environment,
            wrapper_name=wrapper_name,
        )

        logger.debug(
            "Starting stream (container=%s, cmd=%s, timeout=%s)",
            container_name,
            command,
            stream_timeout,
        )

        start_time = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=10 * 1024 * 1024,
        )

        outcome = StreamOutcome()
        try:
            async for line in read_lines(proc, stream_timeout, start_time, outcome):
                yield line
        finally:
            exit_code = await _cleanup_process(proc)
            if outcome.timed_out and exit_code != _resolve_stream_exit_code(
                exit_code, timed_out=outcome.timed_out
            ):
                logger.error(
                    "Stream timed out after %.1fs; reporting exit %d (container=%s)",
                    stream_timeout or -1,
                    _TIMEOUT_EXIT_CODE,
                    container_name,
                )
            exit_code = _resolve_stream_exit_code(exit_code, timed_out=outcome.timed_out)
            self._last_exit_code = exit_code
            if exit_code and exit_code != 0:
                logger.warning(
                    "Stream process exited with code %d (container=%s)",
                    exit_code,
                    container_name,
                )
