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
    AgentVerdict,
    PhaseUsage,
    StreamResult,
    SubagentTracker,
    TokenAccumulator,
)
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
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
        interrupt_reason: str | None = "Cancelled by user",
        launches: bool = True,
        produces: Sequence[tuple[str, bytes]] = (),
        says: str | None = None,
        spent: PhaseUsage | None = None,
        stream_error: str | None = None,
    ) -> None:
        self._interrupt = interrupt
        self._exit_code = exit_code
        self._interrupt_reason = interrupt_reason
        self._launches = launches
        #: What went wrong with the STREAM, as both real stream processors
        #: report it: an ``is_error`` result line from claude, a malformed or
        #: unterminated stream from codex. Independent of ``exit_code``,
        #: because in production the two come apart in both directions - and
        #: the combination that has no other way to be expressed is the one
        #: #1367 is about: a readable refusal whose telemetry is broken is not
        #: evidence the quality gate worked.
        self._stream_error = stream_error
        #: The last thing this agent said on its stream, as the real stream
        #: processors would have captured it. Independent of ``produces``
        #: because in production the two come apart: #1300 is agents that
        #: finished, said what they had done, and wrote no file at all.
        self._says = says
        #: Files this double writes into each phase's workspace before
        #: returning, as (path relative to /workspace, bytes). Empty is the
        #: default and models an agent that produced NOTHING - which is not an
        #: exotic case but the one behind #1167, where a phase completed
        #: without any of the output its contract declared. Writing real files
        #: is what lets a test drive the collection step for real instead of
        #: mocking out the very hop under test.
        self._produces = tuple(produces)
        #: What this agent burned before it returned. Zeros by default, and
        #: settable for the same reason ``produces`` is: a FAILING agent is not
        #: an agent that did nothing. A phase killed at its timeout has spent
        #: real tokens, and until this double could say so the only failures any
        #: test could drive were free ones - the single case where losing the
        #: counts costs nothing to notice (#1262).
        #:
        #: Put on the COMMAND as well as the accumulator, because the command is
        #: what production reads: the real handler resolves the two through
        #: ``FinalUsage`` and writes the answer there, and the failure path reads
        #: it back off the runtime. A double that set only the accumulator would
        #: leave the hop under test reading a zero.
        self._spent = spent or PhaseUsage()
        #: The last thing this double's agent SAYS, verbatim - including its
        #: ``TASK_RESULT`` block if it writes one. Passed through the REAL
        #: `AgentVerdict.from_agent_text` below rather than setting a verdict
        #: directly, so a test that drives a reported failure exercises the
        #: production reader of that report and not a fixture's idea of it
        #: (#1256).
        self._says = says
        self.calls: list[TodoItem] = []
        self.runners: list[Runner] = []

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
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        self.calls.append(todo)
        self.runners.append(runner)
        if self._produces:
            await workspace.inject_files(list(self._produces))
        # Every factory below except ``never_launched`` describes a run whose
        # process existed, so the double reports it the way the real handler
        # does. A fake that stayed silent would leave every session in a test
        # looking like one that never started (#1047, #1065).
        if self._launches and on_launch is not None:
            await on_launch()
        tokens = TokenAccumulator()
        tokens.record(
            self._spent.input_tokens,
            self._spent.output_tokens,
            self._spent.cache_creation_tokens,
            self._spent.cache_read_tokens,
        )
        stream_result = StreamResult(
            line_count=0,
            interrupt_requested=self._interrupt,
            interrupt_reason=self._interrupt_reason if self._interrupt else None,
            verdict=AgentVerdict.from_agent_text(self._says),
            last_agent_message=self._says,
            error_reason=self._stream_error,
        )
        command = AgentExecutionCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id or "",
            session_id=session_id,
            exit_code=self._exit_code,
            input_tokens=self._spent.input_tokens,
            output_tokens=self._spent.output_tokens,
            cache_creation_tokens=self._spent.cache_creation_tokens,
            cache_read_tokens=self._spent.cache_read_tokens,
            # The real handler puts it here as well as on the stream result,
            # because the command is what reaches the event store and the
            # event store is what a restart reads (#1195, #1300). A double
            # that set only the stream result would leave every processor
            # test salvaging from a value production no longer uses.
            last_agent_message=self._says,
        )
        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
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
    def cancelled(cls, reason: str | None = "Cancelled by user") -> FakeAgentExecutionHandler:
        """Simulates a user-initiated cancel signal (``interrupt_requested=True``).

        ``reason=None`` reproduces what ``syn control cancel <id> --force``
        actually sends without ``-r``. That is the case #918 was: the flag used
        to be derived from the reason, so a cancel carrying no message was
        silently dropped. A fake that always supplies a reason cannot exercise
        it, which is why the default is overridable rather than fixed.
        """
        return cls(interrupt=True, interrupt_reason=reason)

    @classmethod
    def success(
        cls,
        produces: Sequence[tuple[str, bytes]] = (),
        says: str | None = None,
        spent: PhaseUsage | None = None,
        stream_error: str | None = None,
    ) -> FakeAgentExecutionHandler:
        """Simulates a clean agent completion (exit code 0).

        ``produces`` are the files the agent leaves in the workspace, normally
        under ``artifacts/output/``. The default writes none: exit code 0 and
        an empty output tree is a real and previously undetected combination,
        so the double must be able to express it.

        ``says`` is the agent's last message. Exit code 0 with a ``says`` that
        reports ``success: false`` is not a contradiction but the defect
        #1256 is about: the harness ran fine and the AGENT said it had failed.

        ``says`` is its last stream message, and is deliberately a SEPARATE
        argument rather than derived from ``produces``. Wrote-nothing-but-said-
        something is the exact shape of #1300 - three implement phases that had
        pushed their branch and only missed the report - and a double that
        could not express it left that combination untestable end to end.

        ``spent`` is what it burned. Exit code 0, a ``says`` reporting
        ``success: false`` and a non-zero ``spent`` is a phase that did real
        work and then refused itself; it leaves through the same door a timeout
        does and lost its counts the same way (#1262).

        ``stream_error`` is what the stream processor found wrong with the
        stream, with exit code 0 regardless. That pairing is not a
        contradiction either: the process ended fine and its telemetry did
        not, which is what stops a refusal beside it counting as a correct
        one (#1367).
        """
        return cls(
            interrupt=False,
            exit_code=0,
            produces=produces,
            says=says,
            spent=spent,
            stream_error=stream_error,
        )

    @classmethod
    def failed(
        cls,
        exit_code: int = 1,
        produces: Sequence[tuple[str, bytes]] = (),
        says: str | None = None,
        spent: PhaseUsage | None = None,
        stream_error: str | None = None,
    ) -> FakeAgentExecutionHandler:
        """Simulates an agent failure with the given non-zero exit code.

        ``produces`` and ``says`` mean what they mean on ``success`` above, and
        are here because a failing agent is not an agent that did nothing. A
        phase whose process died after writing its deliverable leaves the file
        on disk exactly as a successful one does; until this double could
        express that, the only failures any test could drive were empty ones,
        and an empty workspace is the case where losing the output costs
        nothing (#1321).

        ``spent`` is what it burned getting there. ``exit_code=124`` with a
        non-zero ``spent`` is the timeout this exists for: those counts are the
        only thing separating a phase killed mid-work from one that stalled
        (#1262).

        ``stream_error`` is what the stream processor found wrong with the
        stream, as ``StreamResult.error_reason`` carries it.
        """
        return cls(
            interrupt=False,
            exit_code=exit_code,
            produces=produces,
            says=says,
            spent=spent,
            stream_error=stream_error,
        )

    @classmethod
    def never_launched(cls, exit_code: int = 1) -> FakeAgentExecutionHandler:
        """Simulates a phase whose agent process was never created.

        The handler was dispatched and returned a failure, but nothing ever
        ran - a missing container, an image with no such binary, an exec
        refused. This is the only shape that may end up reported to a user as
        a session that never started, and the only one where ``on_launch``
        stays silent (#1047, #1065).
        """
        return cls(interrupt=False, exit_code=exit_code, launches=False)


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
