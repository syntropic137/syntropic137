"""A failed phase must record WHY it failed, in words (#1196).

The session_error observation exists to say that something went wrong. On a
real failing verify phase it said:

    {"operation_type": "session_error", "tool_name": "", "success": true}

Nothing about the failure, and a success verdict. The read half of the fix
lives in `syn_adapters.projections.session_tools_verdict`; this is the write
half, which has to put a message in the row for the read half to find.

The blank came from `str(error)`, which is "" for any exception raised with no
arguments - `Exception()`, `TimeoutError()`, `CancelledError()`. Both guards
here are load-bearing: `describe_exception` names the exception when it will
not name itself, and `SessionLifecycleManager` refuses to write a blank
whoever hands it one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_shared.events import SESSION_ERROR

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class _Recorded:
    observation_type: str
    data: Mapping[str, object]


class _RecordingWriter:
    def __init__(self) -> None:
        self.observations: list[_Recorded] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: object,
        data: Mapping[str, object],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.observations.append(
            _Recorded(
                observation_type=str(getattr(observation_type, "value", observation_type)),
                data=data,
            )
        )


class _FakeRepo:
    async def save(self, _aggregate: object) -> None:
        return None


def _manager(writer: _RecordingWriter):
    from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
        SessionLifecycleManager,
    )

    return SessionLifecycleManager(
        repository=_FakeRepo(),
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="verify",
        agent_provider="claude",
        agent_model="haiku",
        observability=writer,
    )


def _processor():
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
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
        prompt_builder=AsyncMock(return_value="prompt"),
        command_builder=MagicMock(return_value=["claude"]),
        # The failure path never reads the to-do list; the constructor only
        # asserts it is not None. Keeping it a double keeps this domain test
        # free of an adapters import.
        todo_projection=MagicMock(),
    )


async def _fail_a_phase(error: Exception, writer: _RecordingWriter) -> None:
    """Run the real failure path of a phase whose session is open."""
    processor = _processor()
    manager = _manager(writer)
    await manager.start()
    # Reaching into the private failure path deliberately: it is the code
    # under test, and it has no public entry point that does not also run a
    # whole workflow.
    processor._session_managers["verify"] = manager

    await processor._fail_execution(
        error=error,
        aggregate=MagicMock(),
        execution_id="exec-1",
        workflow_id="wf-1",
        phases=[],
        phase_results=[],
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=datetime.now(UTC),
        failed_phase_id="verify",
    )


def _only_session_error(writer: _RecordingWriter) -> Mapping[str, object]:
    errors = [o for o in writer.observations if o.observation_type == SESSION_ERROR]
    assert len(errors) == 1, f"expected exactly one session_error, got {writer.observations}"
    return errors[0].data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failing_phase_records_a_session_error_carrying_the_message() -> None:
    """(a) A failing phase's session_error says what went wrong."""
    writer = _RecordingWriter()
    await _fail_a_phase(RuntimeError("verify phase exited 1"), writer)

    message = str(_only_session_error(writer)["error_message"])
    assert message.strip(), "a session_error with a blank message is the #1196 defect"
    assert "verify phase exited 1" in message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exception_with_no_message_still_records_a_description() -> None:
    """(c) `str(Exception())` is "", and "" is never what gets recorded."""
    writer = _RecordingWriter()
    await _fail_a_phase(TimeoutError(), writer)

    message = str(_only_session_error(writer)["error_message"])
    assert message.strip(), "an unnamed exception must still leave a usable reason"
    assert "TimeoutError" in message, message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_blank_reason_from_any_caller_is_replaced() -> None:
    """The manager is the last gate: no caller can write a blank reason.

    `describe_exception` covers the one caller that exists today. This covers
    the next one, which will pass a string from somewhere else entirely.
    """
    writer = _RecordingWriter()
    manager = _manager(writer)
    await manager.start()

    await manager.complete_failure(error_message="   ")

    data = _only_session_error(writer)
    message = str(data["error_message"])
    assert message.strip()
    assert "failed" in message, message


@pytest.mark.unit
def test_describe_exception_prefers_what_the_exception_said() -> None:
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
        describe_exception,
    )

    assert describe_exception(RuntimeError("boom")) == "boom"
    assert describe_exception(RuntimeError("  boom  ")) == "boom"
    assert describe_exception(RuntimeError()) == "RuntimeError (no message)"
    assert describe_exception(RuntimeError("")) == "RuntimeError (no message)"
