"""Failure-visibility regressions: #891 (why a phase failed) and #894 (silent no-delegation).

Two independent ways a failed run looked fine:

- #891: a codex auth failure was reported as "codex stream ended without a
  terminal turn.completed event" - a symptom, naming the wrong subsystem.
- #894: a phase declaring ``allow_delegation: true`` whose delegate never
  succeeded still reported ``exit_code == 0`` and therefore success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

pytestmark = pytest.mark.unit


# --- Test doubles -------------------------------------------------------------


async def _stream(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


@dataclass
class _NullCollector:
    calls: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    async def record_tool_started(self, **kwargs: object) -> None:
        self.calls.append(("tool_started", kwargs))

    async def record_tool_completed(self, **kwargs: object) -> None:
        self.calls.append(("tool_completed", kwargs))

    async def record_token_usage(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("token_usage", {"args": args, **kwargs}))

    async def record_session_summary(self, **kwargs: object) -> None:
        self.calls.append(("summary", kwargs))

    async def record_subagent_started(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("subagent_started", kwargs))

    async def record_subagent_stopped(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("subagent_stopped", kwargs))


class _NoopWorkspace:
    last_stream_exit_code = 0

    async def interrupt(self) -> bool:
        return True


def _claude_processor() -> EventStreamProcessor:
    return EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id="exec-1",
        phase_id="p-1",
        session_id="sess-1",
        workspace_id="ws-1",
        agent_model="sonnet",
        collector=_NullCollector(),
    )


def _codex_processor() -> CodexStreamProcessor:
    return CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=_NullCollector(),
        controller=None,
        execution_id="exec-1",
        phase_id="p-1",
        session_id="sess-1",
        agent_model="gpt-5.6",
    )


def _bash_tool_use(tool_use_id: str, command: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": f"msg-{tool_use_id}",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": "Bash",
                        "input": {"command": command},
                    }
                ],
            },
        }
    )


def _bash_tool_result(tool_use_id: str, *, is_error: bool) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "is_error": is_error,
                        "content": "bwrap: setting up uid map: Permission denied"
                        if is_error
                        else "done",
                    }
                ]
            },
        }
    )


def _codex_command_events(item_id: str, command: str, exit_code: int) -> tuple[str, str]:
    started = json.dumps(
        {
            "type": "item.started",
            "item": {"id": item_id, "type": "command_execution", "command": command},
        }
    )
    completed = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": item_id,
                "type": "command_execution",
                "command": command,
                "exit_code": exit_code,
                "aggregated_output": "out",
            },
        }
    )
    return started, completed


# --- #891: an accurate reason for a codex auth failure ------------------------


_AUTH_LINE = (
    "ERROR codex_login::auth::manager: Failed to refresh token: 401 Unauthorized "
    '- {"error": "invalid_grant", "code": "refresh_token_reused"}'
)


@pytest.mark.anyio
async def test_codex_auth_failure_line_becomes_the_error_reason() -> None:
    """A 401 on the codex login refresh must name authentication, not the stream shape."""
    processor = _codex_processor()

    result = await processor.process_stream(_stream(_AUTH_LINE), _NoopWorkspace())

    assert result.error_reason is not None
    assert "Authentication failed (HTTP 401)" in result.error_reason
    assert "codex CLI login" in result.error_reason
    # The old, misleading reason must NOT be what an operator sees.
    assert "turn.completed" not in result.error_reason


@pytest.mark.anyio
async def test_inert_codex_noise_is_still_ignored() -> None:
    """Widening what the parser sees must not turn routine log noise into a failure."""
    noise = (
        "warning: --full-auto is deprecated",
        "Reading additional input from stdin...",
        "ERROR codex_models_manager::manager: could not refresh the model list",
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
    )
    processor = _codex_processor()

    result = await processor.process_stream(_stream(*noise), _NoopWorkspace())

    assert result.error_reason is None


@pytest.mark.anyio
async def test_missing_terminal_turn_still_reports_the_stream_reason() -> None:
    """Without a recognised fault the pre-existing stream-shape reason is unchanged."""
    processor = _codex_processor()

    result = await processor.process_stream(_stream("warning: nothing useful"), _NoopWorkspace())

    assert result.error_reason is not None
    assert "turn.completed" in result.error_reason


# --- #894: delegation counting in both stream processors ----------------------


@pytest.mark.anyio
async def test_claude_stream_counts_a_successful_codex_delegation() -> None:
    processor = _claude_processor()

    result = await processor.process_stream(
        _stream(
            _bash_tool_use("tu-1", "codex exec --json 'review the diff'"),
            _bash_tool_result("tu-1", is_error=False),
        ),
        _NoopWorkspace(),
    )

    assert result.delegation_attempts == 1
    assert result.delegation_successes == 1


@pytest.mark.anyio
async def test_claude_stream_counts_a_failed_codex_delegation_as_attempt_only() -> None:
    """The bubblewrap failure from #894: attempted, never succeeded."""
    processor = _claude_processor()

    result = await processor.process_stream(
        _stream(
            _bash_tool_use("tu-1", "codex exec --json 'review the diff'"),
            _bash_tool_result("tu-1", is_error=True),
        ),
        _NoopWorkspace(),
    )

    assert result.delegation_attempts == 1
    assert result.delegation_successes == 0


@pytest.mark.anyio
async def test_claude_stream_ignores_unrelated_bash_commands() -> None:
    processor = _claude_processor()

    result = await processor.process_stream(
        _stream(
            _bash_tool_use("tu-1", "grep -rn codex ."),
            _bash_tool_result("tu-1", is_error=False),
        ),
        _NoopWorkspace(),
    )

    assert result.delegation_attempts == 0
    assert result.delegation_successes == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("exit_code", "expected_successes"),
    [(0, 1), (1, 0)],
)
async def test_codex_stream_counts_claude_p_delegation(
    exit_code: int, expected_successes: int
) -> None:
    started, completed = _codex_command_events("item-1", "claude -p 'review the diff'", exit_code)
    processor = _codex_processor()

    result = await processor.process_stream(_stream(started, completed), _NoopWorkspace())

    assert result.delegation_attempts == 1
    assert result.delegation_successes == expected_successes


@pytest.mark.anyio
async def test_codex_stream_ignores_unrelated_commands() -> None:
    started, completed = _codex_command_events("item-1", "pytest -q", 0)
    processor = _codex_processor()

    result = await processor.process_stream(_stream(started, completed), _NoopWorkspace())

    assert result.delegation_attempts == 0
    assert result.delegation_successes == 0


# --- #894: the phase-level gate ----------------------------------------------


def _make_processor() -> WorkflowExecutionProcessor:
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    return WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=MagicMock(),
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="test prompt"),
        command_builder=MagicMock(return_value=["claude", "--model", "haiku"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
    )


def _stream_result(attempts: int, successes: int) -> StreamResult:
    return StreamResult(
        line_count=1,
        interrupt_requested=False,
        interrupt_reason=None,
        agent_task_result={"success": True, "comments": "delegation failed, but all good"},
        delegation_attempts=attempts,
        delegation_successes=successes,
    )


async def _run_phase(*, allow_delegation: bool, attempts: int, successes: int) -> None:
    """Drive ``_handle_run_agent`` for a clean (exit_code 0) agent run."""
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoAction,
        TodoItem,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        AgentConfiguration,
        ExecutablePhase,
    )

    processor = _make_processor()
    result = MagicMock()
    result.stream_result = _stream_result(attempts, successes)
    result.command = MagicMock(
        exit_code=0,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    result.tokens = TokenAccumulator()

    handler = MagicMock()
    handler.handle = AsyncMock(return_value=result)
    processor._agent_handler = handler
    processor._active_workspaces["p-1"] = MagicMock()
    processor._active_envs["p-1"] = {}
    processor._active_cmds["p-1"] = ["agent"]

    phase = ExecutablePhase(
        phase_id="p-1",
        name="Phase 1",
        order=1,
        agent_config=AgentConfiguration(
            provider="claude",
            allow_delegation=allow_delegation,
        ),
        prompt_template="do it",
    )
    aggregate = MagicMock(workflow_id="wf-1")
    aggregate.uncommitted_events = []

    await processor._handle_run_agent(
        TodoItem(
            execution_id="exec-1",
            action=TodoAction.RUN_AGENT,
            phase_id="p-1",
            session_id="sess-1",
        ),
        phase,
        aggregate,
    )


@pytest.mark.anyio
async def test_phase_passes_when_the_declared_delegation_succeeded() -> None:
    await _run_phase(allow_delegation=True, attempts=1, successes=1)


@pytest.mark.anyio
async def test_phase_fails_when_the_delegation_was_attempted_and_failed() -> None:
    with pytest.raises(RuntimeError, match="Declared delegation did not occur") as excinfo:
        await _run_phase(allow_delegation=True, attempts=1, successes=0)
    # "tried and failed" must be distinguishable from "never tried".
    assert "attempts=1" in str(excinfo.value)


@pytest.mark.anyio
async def test_phase_fails_when_the_delegation_was_never_attempted() -> None:
    with pytest.raises(RuntimeError, match="Declared delegation did not occur") as excinfo:
        await _run_phase(allow_delegation=True, attempts=0, successes=0)
    assert "attempts=0" in str(excinfo.value)


@pytest.mark.anyio
async def test_phase_without_allow_delegation_is_unaffected() -> None:
    await _run_phase(allow_delegation=False, attempts=0, successes=0)
