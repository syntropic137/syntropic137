"""#2227: a codex phase that dies at its workspace's pids limit says so.

exec-f02a26a13856's verify phase ran two parallel builds into the 256 pids
limit. bash reported `fork: Resource temporarily unavailable`, codex could no
longer start processes, and its stream stopped without `turn.completed`. The phase error
read only "codex stream ended without a terminal turn.completed event", which
names a symptom and no subsystem.

These run the REAL handler over a scripted workspace, because the limit the
error names is the workspace's, and the hop that carries it from the
workspace to the stream processor is the one a processor-only test cannot see.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )

pytestmark = pytest.mark.unit

#: Not the 256 default, so a reason that names it can only have read it from
#: the workspace.
_LIMIT = 1024

#: What bash wrote in exec-f02a26a13856's last tool call.
_OUT_OF_PIDS = (
    "/usr/bin/bash: fork: retry: Resource temporarily unavailable\n"
    "/usr/bin/bash: fork: Resource temporarily unavailable\n"
)


class _ScriptedWorkspace:
    """A workspace whose agent emits ``lines``, provisioned with ``pids_limit``."""

    id = "ws-2227"
    last_stream_exit_code = 1

    def __init__(self, lines: list[str], pids_limit: int | None) -> None:
        self._lines = lines
        self.pids_limit = pids_limit

    def stream(self, *_args: object, **_kwargs: object) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for line in self._lines:
                yield line

        return gen()

    async def interrupt(self) -> bool:
        return True

    async def collect_files(self, **_kwargs: object) -> list[tuple[str, bytes]]:
        return []

    async def codex_rollout(self, _session_id: str) -> None:
        return None

    def keep_git_credential_fresh(self, **_kwargs: object) -> contextlib.nullcontext[None]:
        return contextlib.nullcontext()


class _Collector:
    def __getattr__(self, name: str) -> object:
        if name in ("note_agent_activity", "note_observed_model"):
            return lambda *_args, **_kwargs: None

        async def ignore(*_args: object, **_kwargs: object) -> None:
            return

        return ignore


def _command(item_id: str, output: str, exit_code: int) -> str:
    return json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": item_id,
                "type": "command_execution",
                "command": "/bin/bash -lc 'tail -n 5 preflight.log'",
                "aggregated_output": output,
                "exit_code": exit_code,
                "status": "completed",
            },
        }
    )


def _cut_off_after(*commands: str) -> list[str]:
    """A codex stream that runs ``commands`` and stops without `turn.completed`."""
    return ['{"type":"thread.started","thread_id":"t-2227"}', '{"type":"turn.started"}', *commands]


async def _run(lines: list[str], pids_limit: int | None = _LIMIT) -> AgentExecutionResult:
    return await AgentExecutionHandler(controller=None).handle(
        todo=TodoItem(execution_id="exec-2227", action=TodoAction.RUN_AGENT, phase_id="verify"),
        workspace=_ScriptedWorkspace(lines, pids_limit),  # type: ignore[arg-type]
        agent_env={},
        claude_cmd=["agent"],
        session_id="session-2227",
        agent_model="gpt-5.6",
        timeout_seconds=3600,
        collector=_Collector(),  # type: ignore[arg-type]
        runner=AgentRunner.CODEX,
    )


@pytest.mark.asyncio
async def test_a_stream_cut_off_after_running_out_of_pids_names_the_pids_limit() -> None:
    result = await _run(_cut_off_after(_command("item_1", _OUT_OF_PIDS, 254)))

    reason = result.stream_result.error_reason
    assert reason is not None
    assert reason.startswith(
        f"workspace hit its pids limit ({_LIMIT}): bash could not start a process"
    )
    assert "`fork: Resource temporarily unavailable`" in reason
    assert MISSING_TERMINAL_TURN_REASON not in reason


@pytest.mark.asyncio
async def test_without_pids_evidence_the_reason_stays_the_generic_one() -> None:
    result = await _run(_cut_off_after(_command("item_1", "error: build failed\n", 1)))

    assert result.stream_result.error_reason == MISSING_TERMINAL_TURN_REASON


@pytest.mark.asyncio
async def test_running_out_of_pids_followed_by_a_command_that_ran_is_not_the_cause() -> None:
    """The LAST command's output is the evidence: earlier pressure that passed is not."""
    result = await _run(
        _cut_off_after(
            _command("item_1", _OUT_OF_PIDS, 254),
            _command("item_2", "On branch main\n", 0),
        )
    )

    assert result.stream_result.error_reason == MISSING_TERMINAL_TURN_REASON


@pytest.mark.asyncio
async def test_running_out_of_pids_the_turn_survived_fails_nothing() -> None:
    lines = [
        *_cut_off_after(_command("item_1", _OUT_OF_PIDS, 254)),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 1}}),
    ]

    result = await _run(lines)

    assert result.stream_result.error_reason is None


@pytest.mark.asyncio
async def test_an_unrecorded_limit_is_still_named_as_the_pids_limit() -> None:
    result = await _run(_cut_off_after(_command("item_1", _OUT_OF_PIDS, 254)), pids_limit=None)

    reason = result.stream_result.error_reason
    assert reason is not None
    assert reason.startswith("workspace hit its pids limit: bash could not start a process")


@pytest.mark.asyncio
async def test_resource_temporarily_unavailable_alone_is_not_running_out_of_pids() -> None:
    """EAGAIN's text is also a non-blocking read with nothing to read."""
    output = "BlockingIOError: [Errno 11] Resource temporarily unavailable\n"
    result = await _run(_cut_off_after(_command("item_1", output, 1)))

    assert result.stream_result.error_reason == MISSING_TERMINAL_TURN_REASON
