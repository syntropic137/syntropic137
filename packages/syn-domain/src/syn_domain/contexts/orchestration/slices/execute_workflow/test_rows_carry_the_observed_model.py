"""Every usage row names the model the harness REPORTED, never the alias (ADR-067).

The phase declares an alias (``opus``, ``gpt-sol``). The rows each stream
processor writes must carry what the harness said it ran as ``model`` - or None
when it never said - and the alias separately as ``requested_model``, a key that
is ALWAYS present so a reader can tell these rows from legacy ones.

Driven through the REAL ``ObservabilityCollector`` into a recording writer, so
what is asserted is the stored row, not a call a test double saw.

Codex is the interesting half: its stdout never names the model, which is only
learned from the rollout at end-of-stream. Its per-turn rows are therefore held
and written after that read - and must still be written, with whatever model is
known, when the run is cancelled, the stream breaks, the rollout read fails or
the writer fails part-way.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions import ObservationType
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository
from syn_shared.agents import CodexModelAlias, ModelAlias, ModelId
from syn_shared.events import SESSION_ERROR, SESSION_SUMMARY
from syn_shared.observed_model import OBSERVED_MODEL_KEY, REQUESTED_MODEL_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions import RolloutDocument

pytestmark = pytest.mark.unit

CLAUDE_REQUESTED = ModelAlias.OPUS
CLAUDE_REPORTED = ModelId.CLAUDE_OPUS_5_5
SUBAGENT_REPORTED = "claude-haiku-4-5-20251001"
CODEX_REQUESTED = CodexModelAlias.GPT_SOL
CODEX_REPORTED = ModelId.GPT_6_SOL
CODEX_THREAD_ID = "thread-under-test"


@dataclass(frozen=True)
class _Row:
    """One stored observation, reduced to the fields these tests read."""

    observation_type: str
    model: object
    requested_model: object
    has_requested_model: bool
    input_tokens: object


@dataclass
class _RecordingWriter:
    """Records each observation; can be told to fail the Nth token_usage write."""

    rows: list[_Row] = field(default_factory=list)
    fail_token_usage_write: int | None = None
    _token_usage_writes: int = 0

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if observation_type == ObservationType.TOKEN_USAGE:
            self._token_usage_writes += 1
            if self._token_usage_writes == self.fail_token_usage_write:
                msg = "observability backend unreachable"
                raise ConnectionError(msg)
        assert isinstance(data, dict)
        self.rows.append(
            _Row(
                observation_type=str(observation_type),
                model=data.get(OBSERVED_MODEL_KEY),
                requested_model=data.get(REQUESTED_MODEL_KEY),
                has_requested_model=REQUESTED_MODEL_KEY in data,
                input_tokens=data.get("input_tokens"),
            )
        )

    def of(self, observation_type: str) -> list[_Row]:
        return [r for r in self.rows if r.observation_type == observation_type]

    @property
    def usage(self) -> list[_Row]:
        return self.of(ObservationType.TOKEN_USAGE)


class _Workspace:
    async def interrupt(self) -> bool:
        return True


class _Rollout:
    """A `CodexRolloutPort` serving a rollout naming ``model``, or failing."""

    def __init__(self, model: str | None, *, raises: bool = False) -> None:
        self._model = model
        self._raises = raises

    async def codex_rollout(self, native_session_id: str) -> RolloutDocument | None:
        if self._raises:
            msg = "docker exec failed"
            raise RuntimeError(msg)
        if self._model is None:
            return None
        return [{"type": "turn_context", "payload": {"model": self._model}}]


def _collector(writer: _RecordingWriter, requested: str | None) -> ObservabilityCollector:
    return ObservabilityCollector(
        writer=writer,
        session_id="s1",
        execution_id="exec-1",
        phase_id="p1",
        workspace_id="ws-1",
        requested_model=requested,
    )


async def _stream(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


# ---------------------------------------------------------------------------
# claude
# ---------------------------------------------------------------------------


def _claude_init(model: str) -> str:
    return json.dumps({"type": "system", "subtype": "init", "model": model, "session_id": "c-1"})


def _claude_turn(msg_id: str, model: str | None, tokens: int) -> str:
    message = {
        "id": msg_id,
        "content": [{"type": "text", "text": "working"}],
        "usage": {"input_tokens": tokens, "output_tokens": 1},
    }
    named = {"model": model} if model is not None else {}
    return json.dumps({"type": "assistant", "message": {**message, **named}})


async def _run_claude(writer: _RecordingWriter, *lines: str) -> None:
    collector = _collector(writer, CLAUDE_REQUESTED)
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=None,
        controller=None,
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        workspace_id="ws-1",
        agent_model=CLAUDE_REQUESTED,
        collector=collector,
    )
    await processor.process_stream(_stream(*lines), _Workspace())
    await collector.record_session_summary(
        total_cost_usd=None,
        input_tokens=0,
        output_tokens=0,
        cache_creation=0,
        cache_read=0,
        num_turns=None,
        duration_ms=None,
    )


class TestClaudeRows:
    async def test_rows_carry_the_reported_model_and_the_request_apart(self) -> None:
        writer = _RecordingWriter()
        await _run_claude(
            writer, _claude_init(CLAUDE_REPORTED), _claude_turn("m1", CLAUDE_REPORTED, 10)
        )

        [row] = writer.usage
        assert row.model == CLAUDE_REPORTED
        assert row.requested_model == CLAUDE_REQUESTED
        [summary] = writer.of(SESSION_SUMMARY)
        assert summary.model == CLAUDE_REPORTED
        assert summary.requested_model == CLAUDE_REQUESTED

    async def test_a_subagent_turn_is_filed_under_its_own_model(self) -> None:
        """Each row takes the model ITS message names, not the leader's."""
        writer = _RecordingWriter()
        await _run_claude(
            writer,
            _claude_init(CLAUDE_REPORTED),
            _claude_turn("m1", CLAUDE_REPORTED, 10),
            _claude_turn("m2", SUBAGENT_REPORTED, 5),
        )

        assert [r.model for r in writer.usage] == [
            CLAUDE_REPORTED,
            SUBAGENT_REPORTED,
        ]
        # The session is still the leader's: first report wins.
        [summary] = writer.of(SESSION_SUMMARY)
        assert summary.model == CLAUDE_REPORTED

    async def test_a_turn_naming_no_model_takes_the_sessions(self) -> None:
        writer = _RecordingWriter()
        await _run_claude(writer, _claude_init(CLAUDE_REPORTED), _claude_turn("m1", None, 10))

        [row] = writer.usage
        assert row.model == CLAUDE_REPORTED

    async def test_a_stream_that_never_says_leaves_the_model_unknown(self) -> None:
        """Never the alias, and the requested key is still written."""
        writer = _RecordingWriter()
        await _run_claude(writer, _claude_turn("m1", None, 10))

        [row] = writer.usage
        assert row.model is None
        assert row.requested_model == CLAUDE_REQUESTED
        [summary] = writer.of(SESSION_SUMMARY)
        assert summary.model is None
        assert summary.has_requested_model


# ---------------------------------------------------------------------------
# codex
# ---------------------------------------------------------------------------


def _thread_started() -> str:
    return json.dumps({"type": "thread.started", "thread_id": CODEX_THREAD_ID})


def _turn(tokens: int) -> str:
    return json.dumps(
        {"type": "turn.completed", "usage": {"input_tokens": tokens, "output_tokens": 2}}
    )


def _codex(
    writer: _RecordingWriter, rollout: _Rollout | None
) -> tuple[CodexStreamProcessor, TokenAccumulator]:
    tokens = TokenAccumulator()
    processor = CodexStreamProcessor(
        tokens=tokens,
        collector=_collector(writer, CODEX_REQUESTED),
        controller=None,
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        agent_model=CODEX_REQUESTED,
        rollout=rollout,
    )
    return processor, tokens


class TestCodexRows:
    async def test_every_turn_carries_the_model_the_rollout_names(self) -> None:
        writer = _RecordingWriter()
        processor, _ = _codex(writer, _Rollout(CODEX_REPORTED))

        await processor.process_stream(
            _stream(_thread_started(), _turn(10), _turn(20), _turn(30)), _Workspace()
        )

        assert [r.input_tokens for r in writer.usage] == [10, 20, 30]
        assert {r.model for r in writer.usage} == {CODEX_REPORTED}
        assert {r.requested_model for r in writer.usage} == {CODEX_REQUESTED}
        [summary] = writer.of(SESSION_SUMMARY)
        assert summary.model == CODEX_REPORTED
        assert summary.requested_model == CODEX_REQUESTED

    async def test_rows_are_written_before_the_summary(self) -> None:
        """A reader that sees the summary has every row that preceded it."""
        writer = _RecordingWriter()
        processor, _ = _codex(writer, _Rollout(CODEX_REPORTED))

        await processor.process_stream(_stream(_thread_started(), _turn(10)), _Workspace())

        assert [r.observation_type for r in writer.rows] == [
            ObservationType.TOKEN_USAGE,
            SESSION_SUMMARY,
        ]

    async def test_the_live_accumulator_is_not_held_back(self) -> None:
        """Only the ROWS wait for the model; running totals are live."""
        writer = _RecordingWriter()
        processor, tokens = _codex(writer, _Rollout(CODEX_REPORTED))
        seen_mid_stream: list[int] = []

        async def stream() -> AsyncIterator[str]:
            yield _thread_started()
            yield _turn(10)
            seen_mid_stream.append(tokens.input_tokens)
            assert writer.usage == []
            yield _turn(20)

        await processor.process_stream(stream(), _Workspace())

        assert seen_mid_stream == [10]
        assert len(writer.usage) == 2

    async def test_a_truncated_stream_still_writes_its_rows(self) -> None:
        """Cut off before the final turn: the turns it did finish are kept."""
        writer = _RecordingWriter()
        processor, _ = _codex(writer, _Rollout(CODEX_REPORTED))

        await processor.process_stream(
            _stream(_thread_started(), _turn(10), '{"type": "item.star'), _Workspace()
        )

        [row] = writer.usage
        assert row.model == CODEX_REPORTED

    async def test_an_unreadable_rollout_writes_rows_as_unknown(self) -> None:
        writer = _RecordingWriter()
        processor, _ = _codex(writer, _Rollout(None))

        await processor.process_stream(_stream(_thread_started(), _turn(10)), _Workspace())

        [row] = writer.usage
        assert row.model is None
        assert row.requested_model == CODEX_REQUESTED

    async def test_a_rollout_read_that_raises_loses_no_rows(self) -> None:
        writer = _RecordingWriter()
        processor, _ = _codex(writer, _Rollout(CODEX_REPORTED, raises=True))

        with pytest.raises(RuntimeError, match="docker exec failed"):
            await processor.process_stream(
                _stream(_thread_started(), _turn(10), _turn(20)), _Workspace()
            )

        assert [r.input_tokens for r in writer.usage] == [10, 20]
        assert {r.model for r in writer.usage} == {None}

    async def test_a_stream_that_raises_mid_run_loses_no_rows(self) -> None:
        writer = _RecordingWriter()
        processor, _ = _codex(writer, _Rollout(CODEX_REPORTED))

        async def stream() -> AsyncIterator[str]:
            yield _thread_started()
            yield _turn(10)
            msg = "container went away"
            raise OSError(msg)

        with pytest.raises(OSError, match="container went away"):
            await processor.process_stream(stream(), _Workspace())

        [row] = writer.usage
        assert row.input_tokens == 10

    async def test_a_cancelled_run_loses_no_rows(self) -> None:
        writer = _RecordingWriter()
        processor, _ = _codex(writer, _Rollout(CODEX_REPORTED))
        two_turns_in = asyncio.Event()

        async def stream() -> AsyncIterator[str]:
            yield _thread_started()
            yield _turn(10)
            yield _turn(20)
            two_turns_in.set()
            await asyncio.Event().wait()  # the run hangs until cancelled
            yield _turn(30)

        task = asyncio.create_task(processor.process_stream(stream(), _Workspace()))
        await two_turns_in.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert [r.input_tokens for r in writer.usage] == [10, 20]

    async def test_a_failed_row_write_does_not_lose_the_rest(self) -> None:
        """Every held row is attempted; the writer's fault is still raised."""
        writer = _RecordingWriter(fail_token_usage_write=1)
        processor, _ = _codex(writer, _Rollout(CODEX_REPORTED))

        with pytest.raises(ConnectionError):
            await processor.process_stream(
                _stream(_thread_started(), _turn(10), _turn(20), _turn(30)), _Workspace()
            )

        assert [r.input_tokens for r in writer.usage] == [20, 30]

    async def test_cost_is_priced_as_the_reported_model(self) -> None:
        """The rollout's model prices the run, not the alias it was asked as."""
        reported_writer = _RecordingWriter()
        reported, _ = _codex(reported_writer, _Rollout(ModelId.GPT_5_6_SOL))
        result_reported = await reported.process_stream(
            _stream(_thread_started(), _turn(1_000_000)), _Workspace()
        )

        unknown_writer = _RecordingWriter()
        unknown, _ = _codex(unknown_writer, _Rollout(None))
        result_unknown = await unknown.process_stream(
            _stream(_thread_started(), _turn(1_000_000)), _Workspace()
        )

        # Unknown falls back to the request (gpt-sol -> gpt-6-sol rates);
        # the reported gpt-5.6-sol has its own rate card.
        assert result_reported.total_cost_usd is not None
        assert result_unknown.total_cost_usd is not None
        assert result_reported.total_cost_usd != result_unknown.total_cost_usd


# ---------------------------------------------------------------------------
# session_error
# ---------------------------------------------------------------------------


class TestSessionErrorRows:
    async def test_a_failed_session_names_what_ran_and_what_was_asked(self) -> None:
        writer = _RecordingWriter()
        manager = SessionLifecycleManager(
            repository=FakeSessionRepository(),
            session_id="s1",
            workflow_id="wf-1",
            execution_id="exec-1",
            phase_id="p1",
            agent_provider="claude",
            agent_model=CLAUDE_REQUESTED,
            observability=writer,
        )
        await manager.start()
        manager.note_observed_model(CLAUDE_REPORTED)
        await manager.complete_failure(error_message="boom")

        [row] = writer.of(SESSION_ERROR)
        assert row.model == CLAUDE_REPORTED
        assert row.requested_model == CLAUDE_REQUESTED

    async def test_a_session_that_died_before_reporting_is_unknown(self) -> None:
        writer = _RecordingWriter()
        manager = SessionLifecycleManager(
            repository=FakeSessionRepository(),
            session_id="s1",
            workflow_id="wf-1",
            execution_id="exec-1",
            phase_id="p1",
            agent_provider="claude",
            agent_model=CLAUDE_REQUESTED,
            observability=writer,
        )
        await manager.start()
        await manager.complete_failure(error_message="boom")

        [row] = writer.of(SESSION_ERROR)
        assert row.model is None
        assert row.requested_model == CLAUDE_REQUESTED
