"""A codex phase whose workspace ran out of processes says so (#2227).

exec-f02a26a13856: the last command's output was bash failing to start a
process, then codex exited 1 without `turn.completed`, and the phase was
reported as "codex stream ended without a terminal turn.completed event". Each
case feeds raw codex JSONL through the real stream processor and asserts on
the reason it settles, then on what the reason's consumers do with it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.codex_faults import (
    workspace_out_of_processes_in,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    _exit_code_after_codex_verdict,  # pyright: ignore[reportPrivateUsage]
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_retry import (
    retry_lost_terminal_attempt,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _make_processor,  # pyright: ignore[reportPrivateUsage]
    _NoopWorkspace,  # pyright: ignore[reportPrivateUsage]
    _RecordingCollector,  # pyright: ignore[reportPrivateUsage]
)
from syn_domain.contexts.orchestration.slices.execute_workflow.upstream_failure import (
    UPSTREAM_FAILURES,
    UpstreamFailureKind,
)
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
        PhaseRuntime,
    )

pytestmark = pytest.mark.unit

#: exec-f02a26a13856's last command output, as bash wrote it.
_OUT_OF_PROCESSES = (
    "/usr/bin/bash: fork: retry: Resource temporarily unavailable\n" * 4
    + "/usr/bin/bash: fork: Resource temporarily unavailable\n"
)

_TURN_COMPLETED = json.dumps(
    {
        "type": "turn.completed",
        "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5},
    }
)


def _command(output: str, exit_code: int) -> list[str]:
    item = {"id": "cmd-1", "type": "command_execution", "command": "just qa-ci"}
    done = {**item, "aggregated_output": output, "exit_code": exit_code, "status": "failed"}
    return [
        json.dumps({"type": "thread.started", "thread_id": "t-1"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.started", "item": item}),
        json.dumps({"type": "item.completed", "item": done}),
    ]


async def _reason(lines: list[str]) -> str | None:
    async def _stream() -> AsyncIterator[str]:
        for line in lines:
            yield line

    processor, _tokens = _make_processor(_RecordingCollector())
    result = await processor.process_stream(_stream(), _NoopWorkspace())
    return result.error_reason


@pytest.mark.asyncio
async def test_a_stream_cut_off_after_the_pids_ran_out_names_the_cause() -> None:
    reason = await _reason(_command(_OUT_OF_PROCESSES, exit_code=254))

    assert reason == (
        "workspace ran out of processes (pids_limit): a command could not start a "
        "process (/usr/bin/bash: fork: retry: Resource temporarily unavailable); "
        "raise resources.pids_limit for this phase or run fewer gates at once (#2227)"
        f" - {MISSING_TERMINAL_TURN_REASON}"
    )


@pytest.mark.asyncio
async def test_a_stream_that_completes_gains_no_reason_from_the_same_output() -> None:
    """AgentExecutionHandler fails ANY codex phase whose stream carries a reason."""
    assert await _reason([*_command(_OUT_OF_PROCESSES, exit_code=254), _TURN_COMPLETED]) is None


@pytest.mark.asyncio
async def test_a_later_clean_command_clears_it() -> None:
    """Once a command runs cleanly the processes came back; the cut-off was something else."""
    lines = [*_command(_OUT_OF_PROCESSES, exit_code=254), *_command("ok\n", exit_code=0)[2:]]

    assert await _reason(lines) == MISSING_TERMINAL_TURN_REASON


@pytest.mark.asyncio
async def test_prose_about_the_operation_keeps_the_generic_reason() -> None:
    reason = await _reason(_command("fatal: Cannot fork the repository: no access\n", 128))

    assert reason == MISSING_TERMINAL_TURN_REASON


@pytest.mark.parametrize(
    "line",
    [
        "/usr/bin/bash: fork: Resource temporarily unavailable",
        "bash: line 3: fork: retry: Resource temporarily unavailable",
        "sh: 1: Cannot fork",
        "sh: can't fork: Resource temporarily unavailable",
    ],
)
def test_each_shell_spelling_is_recognised(line: str) -> None:
    reason = workspace_out_of_processes_in(f"building...\n{line}\n")

    assert reason is not None
    assert f"({line})" in reason


@pytest.mark.parametrize(
    "output",
    [
        "read: Resource temporarily unavailable",
        "we Cannot fork here, the policy forbids it",
        "fork: Resource temporarily unavailable",  # no shell prefix: quoted, not reported
    ],
)
def test_anything_else_is_not(output: str) -> None:
    assert workspace_out_of_processes_in(output) is None


async def _named_reason() -> str:
    reason = await _reason(_command(_OUT_OF_PROCESSES, exit_code=254))
    assert reason is not None
    return reason


@pytest.mark.asyncio
async def test_it_reads_as_unknown_not_auth_and_not_a_busy_provider() -> None:
    """A workspace limit is ours to fix: no credential prompt, no waiting out codex."""
    assert UPSTREAM_FAILURES.kind_of(await _named_reason()) is UpstreamFailureKind.UNKNOWN


@pytest.mark.asyncio
async def test_it_is_not_retried_as_a_lost_terminal_event() -> None:
    """#1335 retries a stream that only lost its last event; the same limit hits the same wall."""
    todo = MagicMock(phase_id="verify", execution_id="exec-1")

    retried = await retry_lost_terminal_attempt(
        cast("TodoItem", todo),
        cast("WorkflowExecutionAggregate", MagicMock()),
        cast("PhaseRuntime", MagicMock()),
        cast("ExecutionJournal", MagicMock()),
        reason=await _named_reason(),
        failure="phase failed",
    )

    assert retried is False


@pytest.mark.asyncio
async def test_it_fails_the_phase_even_with_a_deliverable() -> None:
    """#1111 completes on a deliverable only for the bare telemetry gap, not this."""
    workspace = MagicMock()
    workspace.collect_files = AsyncMock(
        return_value=[("artifacts/output/deliverable.md", b"# looks done")]
    )
    stream_result = StreamResult(
        line_count=4,
        interrupt_requested=False,
        interrupt_reason=None,
        error_reason=await _named_reason(),
    )

    exit_code = await _exit_code_after_codex_verdict(
        runner=AgentRunner.CODEX,
        stream_result=stream_result,
        exit_code=0,
        workspace=cast("ManagedWorkspace", workspace),
        phase_id="verify",
    )

    assert exit_code == 1
