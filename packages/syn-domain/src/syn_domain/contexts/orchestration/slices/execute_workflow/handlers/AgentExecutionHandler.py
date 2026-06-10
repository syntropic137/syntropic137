"""AgentExecutionHandler — launches container, streams output (ISS-196).

Extracted from WorkflowExecutionEngine stream processing section (lines 961-1001).
Delegates telemetry to ObservabilityCollector.

Reports AgentExecutionCompletedCommand to the aggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from syn_adapters.control import ExecutionController
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )

logger = logging.getLogger(__name__)


class InteractiveCompletionResult(Protocol):
    """Structural view of the driver's AwaitResult (agentic-primitives).

    Only the members this handler reads; the concrete dataclass carries
    more (timed_out, duration_ms, pane, ...).
    """

    @property
    def ready(self) -> bool: ...

    @property
    def reason(self) -> str: ...


@runtime_checkable
class InteractiveTmuxDriver(Protocol):
    """Typed surface of the interactive-tmux driver workspace.

    The concrete class (`interactive_tmux.InteractiveTmuxWorkspace`)
    lives in the agentic-primitives submodule and is intentionally not
    imported here; `provider_handle()` returns it as `Any`. This
    Protocol pins the documented send_message / await_completion /
    capture_response / stop surface so the handler is type-checked
    against it, and `_handle_interactive` validates the handle against
    it at the provider boundary (runtime_checkable: method presence).
    """

    def send_message(self, agent: str, text: str) -> None: ...

    def await_completion(self, agent: str, timeout: float = ...) -> InteractiveCompletionResult: ...

    def capture_response(self, agent: str) -> str: ...

    def stop(self) -> None: ...


def _detect_exit_code(
    stream_result: StreamResult,
    workspace: ManagedWorkspace,
    phase_id: str,
    tokens: TokenAccumulator,
) -> int:
    """Determine agent exit code from stream result and workspace state.

    Note: If interrupt_requested=True, the caller is responsible for routing
    to the cancellation path. This function returns only the actual process
    exit code.
    """
    stream_exit_code = workspace.last_stream_exit_code
    if stream_exit_code is not None and stream_exit_code != 0:
        logger.error(
            "Agent CLI exited with code %d (phase=%s, lines=%d)",
            stream_exit_code,
            phase_id,
            stream_result.line_count,
        )
        return stream_exit_code
    if tokens.input_tokens == 0 and tokens.output_tokens == 0:
        logger.warning(
            "Agent produced 0 tokens (phase=%s, lines=%d) — CLI may have failed to start",
            phase_id,
            stream_result.line_count,
        )
    return 0


class AgentExecutionResult:
    """Result of agent execution."""

    __slots__ = ("command", "stream_result", "subagents", "tokens")

    def __init__(
        self,
        stream_result: StreamResult,
        tokens: TokenAccumulator,
        subagents: SubagentTracker,
        command: AgentExecutionCompletedCommand,
    ) -> None:
        self.stream_result = stream_result
        self.tokens = tokens
        self.subagents = subagents
        self.command = command


class AgentExecutionHandler:
    """Launches agent in container, streams output via EventStreamProcessor.

    Reports AgentExecutionCompletedCommand.
    """

    def __init__(
        self,
        controller: ExecutionController | None,
    ) -> None:
        self._controller = controller

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
        interactive_prompt: str | None = None,
    ) -> AgentExecutionResult:
        """Run agent in workspace and stream output.

        Dispatch:
          * `interactive_prompt is None` (default) → claude -p path:
            stream `claude_cmd` through the workspace, parse stream-json
            into Lane-2 events.
          * `interactive_prompt is not None` → interactive-tmux path:
            drive the workspace's interactive-tmux driver via
            send_message / await_completion / capture_response and
            synthesize a single Lane-2 capture event. Token/cost
            accounting is not available on this path in v1
            (see docs/plans/interactive-tmux-integration.md §7).
        """
        assert todo.phase_id is not None

        tokens = TokenAccumulator()
        subagents = SubagentTracker()

        if interactive_prompt is not None:
            return await self._handle_interactive(
                todo=todo,
                workspace=workspace,
                tokens=tokens,
                subagents=subagents,
                prompt=interactive_prompt,
                session_id=session_id,
                timeout_seconds=timeout_seconds,
                collector=collector,
            )

        processor = EventStreamProcessor(
            tokens=tokens,
            subagents=subagents,
            observability=None,  # Not used when collector is provided
            controller=self._controller,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            session_id=session_id,
            workspace_id=getattr(workspace, "id", None),
            agent_model=agent_model,
            collector=collector,
        )

        stream_result = await processor.process_stream(
            workspace.stream(
                claude_cmd,
                timeout_seconds=timeout_seconds,
                environment=agent_env,
            ),
            workspace,
        )

        exit_code = _detect_exit_code(stream_result, workspace, todo.phase_id, tokens)

        # ISS-217: Emit session_summary with authoritative CLI totals (Lane 2)
        if collector is not None:
            await collector.record_session_summary(
                total_cost_usd=stream_result.total_cost_usd,
                input_tokens=stream_result.result_input_tokens,
                output_tokens=stream_result.result_output_tokens,
                cache_creation=stream_result.result_cache_creation,
                cache_read=stream_result.result_cache_read,
                num_turns=stream_result.num_turns,
                duration_ms=stream_result.duration_ms,
            )

        # Prefer result event totals (authoritative) over accumulated per-turn counts
        final_input = stream_result.result_input_tokens or tokens.input_tokens
        final_output = stream_result.result_output_tokens or tokens.output_tokens
        final_cache_creation = stream_result.result_cache_creation or tokens.cache_creation_tokens
        final_cache_read = stream_result.result_cache_read or tokens.cache_read_tokens

        command = AgentExecutionCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            session_id=session_id,
            exit_code=exit_code,
            input_tokens=final_input,
            output_tokens=final_output,
            cache_creation_tokens=final_cache_creation,
            cache_read_tokens=final_cache_read,
        )

        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=command,
        )

    async def _handle_interactive(
        self,
        *,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        tokens: TokenAccumulator,
        subagents: SubagentTracker,
        prompt: str,
        session_id: str,
        timeout_seconds: int,
        collector: ObservabilityCollector | None,
    ) -> AgentExecutionResult:
        """Drive a claude-interactive phase through send_message/await_completion.

        Routes through `InteractiveTmuxIsolationAdapter.provider_handle(...)`
        — public accessor, no `_handle` reach-ins. Falls back to the
        standard agent path with a recorded error if the workspace is
        not actually backed by the interactive provider.

        Cancel responsiveness (fix for D-block-1, surfaced by the
        stress campaign 2026-06-10): the driver's `await_completion`
        is a synchronous blocking call running in a worker thread.
        While it runs, we poll `ExecutionController.check_signal` on
        the asyncio loop. If a CANCEL signal arrives, we tear down
        the workspace (which unblocks the driver's `docker exec
        tmux capture-pane` by removing the container) and return
        an `AgentExecutionResult` with
        `stream_result.interrupt_requested=True` so the
        WorkflowExecutionProcessor routes through
        `_handle_cancel_signal` → `aggregate.cancel_execution`.
        """
        assert todo.phase_id is not None

        adapter = getattr(workspace, "_service", None)
        adapter = getattr(adapter, "_isolation", None)
        get_handle = getattr(adapter, "provider_handle", None)
        # Boundary validation: provider_handle() returns Any (the concrete
        # driver lives in the agentic-primitives submodule); narrow it to
        # the typed Protocol here so everything downstream is type-checked.
        driver: InteractiveTmuxDriver | None = None
        if callable(get_handle):
            handle = get_handle(workspace.isolation_handle)
            if isinstance(handle, InteractiveTmuxDriver):
                driver = handle

        if driver is None:
            return _interactive_driver_unavailable(
                todo=todo, session_id=session_id, tokens=tokens, subagents=subagents
            )

        return await _run_interactive_driver(
            driver=driver,
            todo=todo,
            tokens=tokens,
            subagents=subagents,
            prompt=prompt,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            collector=collector,
            controller=self._controller,
        )


def _interactive_driver_unavailable(
    *,
    todo: TodoItem,
    session_id: str,
    tokens: TokenAccumulator,
    subagents: SubagentTracker,
) -> AgentExecutionResult:
    """Return an AgentExecutionResult representing a wiring failure.

    The provided workspace does not expose an interactive-tmux driver
    (typically a config mismatch: SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED is
    off, or the provider_kind is not "interactive-tmux"). We surface a
    typed error_reason rather than crashing the processor.
    """
    assert todo.phase_id is not None
    error_msg = (
        "interactive-tmux dispatch invoked but the workspace's "
        "isolation backend does not expose provider_handle returning "
        "an InteractiveTmuxDriver (expected InteractiveTmuxIsolationAdapter). "
        "Check SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED and "
        "WorkspaceServiceConfig.provider_kind."
    )
    logger.error(error_msg)
    stream_result = StreamResult(
        line_count=0,
        interrupt_requested=False,
        interrupt_reason=None,
        agent_task_result=None,
        error_reason=error_msg,
    )
    command = AgentExecutionCompletedCommand(
        execution_id=todo.execution_id,
        phase_id=todo.phase_id,
        session_id=session_id,
        exit_code=1,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    return AgentExecutionResult(
        stream_result=stream_result,
        tokens=tokens,
        subagents=subagents,
        command=command,
    )


async def _run_interactive_driver(
    *,
    driver: InteractiveTmuxDriver,
    todo: TodoItem,
    tokens: TokenAccumulator,
    subagents: SubagentTracker,
    prompt: str,
    session_id: str,
    timeout_seconds: int,
    collector: ObservabilityCollector | None,
    controller: ExecutionController | None,
) -> AgentExecutionResult:
    """Send the prompt, wait for completion, capture pane — with cancel polling.

    Implementation note (D-block-1 fix): the driver's
    `await_completion` is synchronous and blocking. We run it in a
    worker thread via `loop.run_in_executor` and concurrently poll
    `controller.check_signal` on the asyncio loop. On CANCEL we call
    `driver.stop()` which removes the workspace container; that
    causes the in-flight `docker exec tmux capture-pane` inside the
    executor to raise CalledProcessError, returning control to us.

    On any thread-side subprocess failure we wrap the exception into
    a typed `InteractiveTmuxTransportError` (D2 fix) so the workflow's
    error_message is operator-readable instead of a raw Python repr.
    """
    import asyncio

    assert todo.phase_id is not None
    loop = asyncio.get_running_loop()

    def _drive() -> tuple[int, str, str]:
        from subprocess import CalledProcessError

        try:
            driver.send_message("claude", prompt)
            result = driver.await_completion("claude", timeout=float(timeout_seconds))
            pane = driver.capture_response("claude")
        except CalledProcessError as exc:
            # D2: convert raw subprocess errors to a typed domain error
            # so error_message is not a raw Python repr leaking the
            # docker-exec arglist.
            raise InteractiveTmuxTransportError.from_called_process(exc) from exc
        exit_code = 0 if result.ready else 124  # 124 = standard timeout exit code
        reason = getattr(result, "reason", "ready" if result.ready else "timeout")
        return exit_code, pane, reason

    completion_future = loop.run_in_executor(None, _drive)

    cancel_signal_obj = await _race_completion_against_cancel(
        completion_future=completion_future,
        controller=controller,
        execution_id=todo.execution_id,
        driver=driver,
    )

    if cancel_signal_obj is not None:
        return _build_cancelled_result(
            todo=todo,
            session_id=session_id,
            tokens=tokens,
            subagents=subagents,
            cancel_signal=cancel_signal_obj,
        )

    try:
        exit_code, pane, reason = await completion_future
    except InteractiveTmuxTransportError as exc:
        logger.error(
            "interactive-tmux transport error (phase=%s): %s",
            todo.phase_id,
            exc,
        )
        return _build_failed_result(
            todo=todo,
            session_id=session_id,
            tokens=tokens,
            subagents=subagents,
            error_reason=str(exc),
        )

    if collector is not None:
        await collector.record_session_summary(
            total_cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            cache_creation=0,
            cache_read=0,
            num_turns=1,
            duration_ms=0,
        )

    logger.info(
        "interactive-tmux phase finished (phase=%s, exit=%d, reason=%s, pane_chars=%d)",
        todo.phase_id,
        exit_code,
        reason,
        len(pane),
    )

    stream_result = StreamResult(
        line_count=1,
        interrupt_requested=False,
        interrupt_reason=None,
        agent_task_result=None,
        num_turns=1,
    )
    command = AgentExecutionCompletedCommand(
        execution_id=todo.execution_id,
        phase_id=todo.phase_id,
        session_id=session_id,
        exit_code=exit_code,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    return AgentExecutionResult(
        stream_result=stream_result,
        tokens=tokens,
        subagents=subagents,
        command=command,
    )


async def _race_completion_against_cancel(
    *,
    completion_future: object,
    controller: ExecutionController | None,
    execution_id: str,
    driver: InteractiveTmuxDriver,
) -> object | None:
    """Poll for a CANCEL signal while the driver runs.

    Returns the CANCEL signal object if cancellation was requested,
    otherwise None when the completion_future finishes naturally.

    On CANCEL we invoke `driver.stop()` which removes the workspace
    container — the in-flight `docker exec ... tmux capture-pane`
    inside the executor then raises CalledProcessError, returning
    control to the caller.
    """
    import asyncio

    # NOTE: the cast is purely for type-checker clarity.
    from typing import cast

    from syn_adapters.control.commands import ControlSignalType

    fut = cast("asyncio.Future[object]", completion_future)
    poll_interval_s = 0.5
    while not fut.done():
        if controller is not None:
            try:
                signal = await controller.check_signal(execution_id)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Cancel signal check failed (exec=%s): %s", execution_id, exc)
                signal = None
            if (
                signal is not None
                and getattr(signal, "signal_type", None) == ControlSignalType.CANCEL
            ):
                logger.info(
                    "Cancel signal received during interactive phase (exec=%s, reason=%s)",
                    execution_id,
                    getattr(signal, "reason", None),
                )
                # Tear down the workspace to unblock the driver thread.
                try:
                    await asyncio.to_thread(driver.stop)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "driver.stop on cancel raised (exec=%s): %s",
                        execution_id,
                        exc,
                    )
                # Give the driver thread a beat to unwind.
                try:
                    await asyncio.wait_for(fut, timeout=10.0)
                except TimeoutError:
                    logger.warning(
                        "Driver thread did not exit within 10s after cancel (exec=%s)",
                        execution_id,
                    )
                except Exception as exc:
                    # Expected: the thread errored because the container is gone.
                    logger.debug(
                        "Driver thread unwound with error after cancel (exec=%s): %s",
                        execution_id,
                        exc,
                    )
                return signal
        try:
            await asyncio.wait_for(asyncio.shield(fut), timeout=poll_interval_s)
        except TimeoutError:
            continue
        except Exception:
            return None
    return None


def _build_cancelled_result(
    *,
    todo: TodoItem,
    session_id: str,
    tokens: TokenAccumulator,
    subagents: SubagentTracker,
    cancel_signal: object,
) -> AgentExecutionResult:
    """Build the AgentExecutionResult for a cancel-during-interactive case.

    `interrupt_requested=True` routes the WorkflowExecutionProcessor
    through `_handle_cancel_signal` → `aggregate.cancel_execution`.
    """
    assert todo.phase_id is not None
    reason = getattr(cancel_signal, "reason", None) or "Cancelled by control plane"
    logger.info(
        "interactive-tmux phase cancelled (phase=%s, reason=%s)",
        todo.phase_id,
        reason,
    )
    stream_result = StreamResult(
        line_count=0,
        interrupt_requested=True,
        interrupt_reason=reason,
        agent_task_result=None,
        num_turns=0,
    )
    command = AgentExecutionCompletedCommand(
        execution_id=todo.execution_id,
        phase_id=todo.phase_id,
        session_id=session_id,
        exit_code=130,  # 128 + SIGINT(2) — convention for cancelled
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    return AgentExecutionResult(
        stream_result=stream_result,
        tokens=tokens,
        subagents=subagents,
        command=command,
    )


def _build_failed_result(
    *,
    todo: TodoItem,
    session_id: str,
    tokens: TokenAccumulator,
    subagents: SubagentTracker,
    error_reason: str,
) -> AgentExecutionResult:
    """Build the AgentExecutionResult for a transport-failure case."""
    assert todo.phase_id is not None
    stream_result = StreamResult(
        line_count=0,
        interrupt_requested=False,
        interrupt_reason=None,
        agent_task_result=None,
        error_reason=error_reason,
    )
    command = AgentExecutionCompletedCommand(
        execution_id=todo.execution_id,
        phase_id=todo.phase_id,
        session_id=session_id,
        exit_code=1,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    return AgentExecutionResult(
        stream_result=stream_result,
        tokens=tokens,
        subagents=subagents,
        command=command,
    )


class InteractiveTmuxTransportError(RuntimeError):
    """Typed domain error for a docker-exec/tmux subprocess failure.

    Wraps `subprocess.CalledProcessError` so the workflow's
    `error_message` is operator-readable (no raw Python repr of the
    docker-exec arglist) and downstream consumers can distinguish a
    transport failure from a model-level failure.
    """

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code

    @classmethod
    def from_called_process(cls, exc: object) -> InteractiveTmuxTransportError:
        """Construct from a subprocess.CalledProcessError without leaking the arglist."""
        rc = int(getattr(exc, "returncode", 1) or 1)
        cmd = getattr(exc, "cmd", None)
        # Surface only the OUTER command (e.g. "docker exec ... tmux capture-pane")
        # rather than the full Python list repr.
        if isinstance(cmd, list) and cmd:
            head = " ".join(str(c) for c in cmd[:4])
            if len(cmd) > 4:
                head = f"{head} …"
        else:
            head = "interactive workspace command"
        # rc=137 = SIGKILL (container killed mid-exec).
        kind = "workspace terminated mid-execution" if rc == 137 else f"failed with exit code {rc}"
        return cls(
            f"Interactive workspace transport error ({head} {kind}).",
            exit_code=rc,
        )
