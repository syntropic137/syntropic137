# ruff: noqa: ARG002  — Protocol implementation; unused params are required by the interface.
"""Sync-safe test double for AgentExecutionHandler.

The module-level type assertion at the bottom of this file ensures pyright verifies
that ``FakeAgentExecutionHandler`` satisfies ``AgentHandlerProtocol``. If
``AgentExecutionHandler.handle()`` ever changes its signature, the Protocol is updated,
this module fails the type-check, and CI catches the drift — not a silent runtime bug.

Usage::

    from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

    handler = FakeAgentExecutionHandler.cancelled()
    processor = WorkflowExecutionProcessor(..., agent_handler=handler)
    result = await processor.run(...)
    assert result.status == "cancelled"
    assert handler.call_count == 1
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import (
    AgentExecutionCompletedCommand,
    AgentExecutionResult,
    StreamResult,
    SubagentTracker,
    TokenAccumulator,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
    )


class FakeAgentExecutionHandler:
    """Configurable, sync-safe test double for ``AgentExecutionHandler``.

    Prefer the factory classmethods for readable test setup:

    - ``FakeAgentExecutionHandler.cancelled()`` — simulates a user cancel signal
    - ``FakeAgentExecutionHandler.success()`` — simulates clean completion
    - ``FakeAgentExecutionHandler.failed(exit_code=1)`` — simulates agent failure

    After running, inspect ``call_count`` or ``calls`` to assert how many phases
    were attempted and which ``TodoItem`` each one received.
    """

    def __init__(
        self,
        *,
        interrupt: bool = False,
        exit_code: int = 0,
    ) -> None:
        self._interrupt = interrupt
        self._exit_code = exit_code
        self.calls: list[TodoItem] = []

    # ------------------------------------------------------------------
    # Protocol-required method
    # ------------------------------------------------------------------

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
    ) -> AgentExecutionResult:
        self.calls.append(todo)
        stream_result = StreamResult(
            line_count=0,
            interrupt_requested=self._interrupt,
            interrupt_reason="Cancelled by user" if self._interrupt else None,
            agent_task_result=None,
        )
        command = AgentExecutionCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id or "",
            session_id=session_id,
            exit_code=self._exit_code,
        )
        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            command=command,
        )

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def call_count(self) -> int:
        """Number of times ``handle()`` has been invoked."""
        return len(self.calls)

    # ------------------------------------------------------------------
    # Factory classmethods
    # ------------------------------------------------------------------

    @classmethod
    def cancelled(cls) -> FakeAgentExecutionHandler:
        """Simulates a user-initiated cancel signal (``interrupt_requested=True``)."""
        return cls(interrupt=True)

    @classmethod
    def success(cls) -> FakeAgentExecutionHandler:
        """Simulates a clean agent completion (exit code 0)."""
        return cls(interrupt=False, exit_code=0)

    @classmethod
    def failed(cls, exit_code: int = 1) -> FakeAgentExecutionHandler:
        """Simulates an agent failure with the given non-zero exit code."""
        return cls(interrupt=False, exit_code=exit_code)


# ---------------------------------------------------------------------------
# Structural type assertion
# ---------------------------------------------------------------------------
# pyright verifies FakeAgentExecutionHandler satisfies AgentHandlerProtocol here.
# Any signature drift on the real AgentExecutionHandler.handle() will update the
# Protocol definition, causing this line to fail type-checking — caught by CI before
# a silent runtime mismatch reaches production.
#
# ``from __future__ import annotations`` makes the annotation a string, so
# AgentHandlerProtocol does not need to be imported at runtime — TYPE_CHECKING only.
_: AgentHandlerProtocol = FakeAgentExecutionHandler()
