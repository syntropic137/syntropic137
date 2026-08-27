"""#891: a failed phase must say WHY it failed, accurately.

The codex CLI announces a login failure only as a plain-text tracing line on
stdout, which the parser used to discard as inert noise. The failure then
surfaced as "codex stream ended without a terminal turn.completed event": a
true statement about a symptom that names the parser rather than the fault.

The tests here pin BOTH directions, because the first draft of the fix only
had the first and would have failed working runs:

- an actual, unrecovered auth failure must be reported as one, and
- a healthy or recovered codex run must NOT be.

The second matters because AgentExecutionHandler forces exit code 1 whenever a
codex stream carries any error_reason, so an over-eager matcher fails
successful phases.

The delegation counters are exercised here too, but ONLY as telemetry. Nothing
gates on them - see the syn_shared.delegation module docstring for why they are
not sound enough to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
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


def _turn_completed() -> str:
    return json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})


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


# --- #891: an accurate reason, and no reason when there is no fault -----------

# The exact line from the production run that motivated the issue.
_PRODUCTION_401 = (
    "ERROR codex_login::auth::manager: Failed to refresh token: 401 Unauthorized "
    '- {"error": "invalid_grant", "code": "refresh_token_reused"}'
)
# A healthy line from the SAME subsystem. The subsystem name alone must never
# be treated as evidence of a fault.
_HEALTHY_LOGIN = "INFO codex_login::auth::manager: loaded cached credentials"
# A real diagnostic from the golden fixture: error severity, nothing to do with auth.
_GENERIC_ERROR = "ERROR codex_models_manager::manager: could not refresh the model list"


@pytest.mark.anyio
async def test_unrecovered_auth_failure_is_reported_as_authentication() -> None:
    """The production 401 with no terminal turn must name authentication."""
    processor = _codex_processor()

    result = await processor.process_stream(_stream(_PRODUCTION_401), _NoopWorkspace())

    assert result.error_reason is not None
    assert "Authentication failed (HTTP 401)" in result.error_reason
    assert "codex CLI login" in result.error_reason
    # The old, misleading reason must NOT be what an operator sees.
    assert "turn.completed" not in result.error_reason


@pytest.mark.anyio
async def test_healthy_login_line_does_not_fail_a_successful_phase() -> None:
    """An INFO line from the auth subsystem is not a fault.

    Regression guard: an earlier draft ORed its alternatives, so the bare
    subsystem name matched and this run - which completes normally - would
    have been forced to exit code 1.
    """
    processor = _codex_processor()

    result = await processor.process_stream(
        _stream(_HEALTHY_LOGIN, _turn_completed()), _NoopWorkspace()
    )

    assert result.error_reason is None


@pytest.mark.anyio
async def test_transient_auth_error_followed_by_a_terminal_turn_succeeds() -> None:
    """A recovered auth error must not fail the phase.

    The CLI retried and reached a normal turn.completed, so whatever it
    complained about mid-stream did not stop the run.
    """
    processor = _codex_processor()

    result = await processor.process_stream(
        _stream(_PRODUCTION_401, _turn_completed()), _NoopWorkspace()
    )

    assert result.error_reason is None


@pytest.mark.anyio
async def test_generic_error_line_keeps_the_stream_shape_reason() -> None:
    """Error severity alone is not an auth fault.

    It still fails (no terminal turn arrived) but must not be mislabelled as
    an authentication problem, which would send an operator to the wrong place.
    """
    processor = _codex_processor()

    result = await processor.process_stream(_stream(_GENERIC_ERROR), _NoopWorkspace())

    assert result.error_reason is not None
    assert "Authentication failed" not in result.error_reason
    assert "turn.completed" in result.error_reason


@pytest.mark.anyio
async def test_healthy_login_line_without_a_terminal_turn_is_not_an_auth_fault() -> None:
    """Failing for a different reason must not be blamed on auth."""
    processor = _codex_processor()

    result = await processor.process_stream(_stream(_HEALTHY_LOGIN), _NoopWorkspace())

    assert result.error_reason is not None
    assert "Authentication failed" not in result.error_reason


@pytest.mark.anyio
async def test_inert_codex_noise_is_still_ignored() -> None:
    """Widening what the parser sees must not turn routine log noise into a failure."""
    processor = _codex_processor()

    result = await processor.process_stream(
        _stream(
            "warning: --full-auto is deprecated",
            "Reading additional input from stdin...",
            _GENERIC_ERROR,
            _turn_completed(),
        ),
        _NoopWorkspace(),
    )

    assert result.error_reason is None


# --- Delegation counters: TELEMETRY ONLY, nothing gates on these --------------


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
async def test_claude_stream_does_not_double_count_a_repeated_tool_result() -> None:
    processor = _claude_processor()

    result = await processor.process_stream(
        _stream(
            _bash_tool_use("tu-1", "codex exec 'go'"),
            _bash_tool_result("tu-1", is_error=False),
            _bash_tool_result("tu-1", is_error=False),
        ),
        _NoopWorkspace(),
    )

    assert result.delegation_attempts == 1
    assert result.delegation_successes == 1


@pytest.mark.anyio
@pytest.mark.parametrize(("exit_code", "expected_successes"), [(0, 1), (1, 0)])
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


@pytest.mark.anyio
async def test_codex_stream_does_not_double_count_a_repeated_item_completed() -> None:
    started, completed = _codex_command_events("item-1", "claude -p 'go'", 0)
    processor = _codex_processor()

    result = await processor.process_stream(
        _stream(started, completed, completed), _NoopWorkspace()
    )

    assert result.delegation_attempts == 1
    assert result.delegation_successes == 1
