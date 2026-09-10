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
class _SessionError:
    """The three fields `_record_terminal_status` writes, read back by name.

    Reading by attribute instead of by key is what makes a lost field fail:
    `data["error_message"]` on a payload that no longer carries one raises
    somewhere inside the manager's own `except Exception`, which swallows it.
    `from_payload` runs in the test body, where a missing key is reported as a
    missing key. #1196 was exactly a field that went absent and read back blank.
    """

    status: str
    error_message: str
    model: str | None

    @classmethod
    def from_payload(cls, data: Mapping[str, str | None]) -> _SessionError:
        status, message = data.get("status"), data.get("error_message")
        assert isinstance(status, str), f"session_error carries no status: {data}"
        assert isinstance(message, str), f"session_error carries no error_message: {data}"
        return cls(status=status, error_message=message, model=data.get("model"))


@dataclass(frozen=True)
class _Recorded:
    observation_type: str
    data: Mapping[str, str | None]


class _RecordingWriter:
    def __init__(self) -> None:
        self.observations: list[_Recorded] = []

    async def record_observation(
        self,
        session_id: str,
        observation_type: object,
        data: Mapping[str, str | None],
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
    processor._runtime.begin("verify", session_manager=manager, started_at=datetime.now(UTC))

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


def _only_session_error(writer: _RecordingWriter) -> _SessionError:
    errors = [o for o in writer.observations if o.observation_type == SESSION_ERROR]
    assert len(errors) == 1, f"expected exactly one session_error, got {writer.observations}"
    return _SessionError.from_payload(errors[0].data)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failing_phase_records_a_session_error_carrying_the_message() -> None:
    """(a) A failing phase's session_error says what went wrong."""
    writer = _RecordingWriter()
    await _fail_a_phase(RuntimeError("verify phase exited 1"), writer)

    message = _only_session_error(writer).error_message
    assert message.strip(), "a session_error with a blank message is the #1196 defect"
    assert "verify phase exited 1" in message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exception_with_no_message_still_records_a_description() -> None:
    """(c) `str(Exception())` is "", and "" is never what gets recorded."""
    writer = _RecordingWriter()
    await _fail_a_phase(TimeoutError(), writer)

    message = _only_session_error(writer).error_message
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

    message = _only_session_error(writer).error_message
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_every_record_of_the_failure_says_the_same_thing() -> None:
    """(d) The session_error was one of FOUR sinks `str(error)` left blank.

    A failing run writes the same failure down four times - the `PhaseResult`
    in the returned execution result, the `session_error` observation, the
    `FailExecutionCommand` the aggregate stores, and the result's own
    `error_message`. #1196 was reported against one of them, but all four read
    `str(error)`, so fixing only the reported one would have left the identical
    defect in three.

    `TimeoutError()` is the fixture because it CANNOT arise from the old code:
    `str(TimeoutError())` is "", so every assertion below was the empty string
    before the description existed. A message-carrying exception would pass
    against either version and prove nothing.

    This also pins the hop `test_phase_outcome` names as its known gap - the
    lines in `_fail_execution` that append the phase result. The description is
    derived in `phase_outcome.failed_phase_outcome` now; if that move ever
    stops feeding any one of these four, exactly one assertion here fails and
    names which sink lost it.
    """
    writer = _RecordingWriter()
    processor = _processor()
    manager = _manager(writer)
    await manager.start()
    # A recorded start is what makes a PhaseResult exist at all; without it
    # `failed_phase_outcome` correctly returns none and this test would assert
    # over an empty list.
    processor._runtime.begin("verify", session_manager=manager, started_at=datetime.now(UTC))
    aggregate = MagicMock()

    result = await processor._fail_execution(
        error=TimeoutError(),
        aggregate=aggregate,
        execution_id="exec-1",
        workflow_id="wf-1",
        phases=[],
        phase_results=[],
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=datetime.now(UTC),
        failed_phase_id="verify",
    )

    [phase_result] = result.phase_results
    command = aggregate.fail_execution.call_args.args[0]

    assert "TimeoutError" in phase_result.error_message, "the phase result lost the reason"
    assert result.error_message and "TimeoutError" in result.error_message, "the result lost it"
    assert "TimeoutError" in command.error, "the stored failure event lost it"
    assert command.error_type == "TimeoutError", "the event's error_type lost it"
    assert "TimeoutError" in _only_session_error(writer).error_message, "the observation lost it"
