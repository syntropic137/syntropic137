"""The model stamped on an artifact is the one the harness ANNOUNCED (#1284).

A cross-model review proves nothing unless the record names the models that ran,
and the tempting value to record is the one the phase asked for: it is already
in `agent_config`, it is in scope at collection time, and it is right most of
the time. It is also not an observation. A codex phase ignores a forwarded
claude model entirely, and a delegated sub-agent may run on a different model
than its parent - so "requested" written under the name "ran" would read as
evidence in exactly the cases where there is none, which is worse than the field
being absent.

So each processor below is constructed with a REQUESTED model and fed a stream
announcing a different one, and every assertion is about which of the two comes
out. The requested value never does, including when the stream says nothing at
all.

BOTH HARNESSES ARE HERE ON PURPOSE. The second model in this platform is always
codex - it runs implement's verify phase and review's falsify phase - so a
cross-model claim that can name only the claude side is no more provable than
one that can name neither. The codex cases sit beside the claude ones rather
than in a file of their own because they are the same claim about the other half
of it, and the pair is what a reader needs to see at once.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions import RolloutDocument

from syn_domain.contexts.artifacts import AgentIdentity
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_artifact_collector import (
    MockArtifactRepo,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_artifact_collector import (
    MockWorkspace as CollectedWorkspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _FIXTURES_DIR,
    _RecordingCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _lines as _file_to_stream,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _make_processor as _make_codex_processor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    MockWorkspace,
    _lines_to_stream,
    _make_processor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_workflow_execution_processor import (
    _make_processor as _make_workflow_processor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

pytestmark = pytest.mark.unit

#: What `_make_processor` passes as `agent_model` — the value the phase asked
#: for. Nothing in this file may ever produce it.
REQUESTED = "claude-sonnet"
ANNOUNCED = "claude-sonnet-4-5-20250929"
LATER = "claude-haiku-4-5-20251001"


def _system_line(model: object) -> str:
    return json.dumps({"type": "system", "subtype": "init", "model": model})


def _assistant_line(model: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"model": model, "content": [{"type": "text", "text": "working"}]},
        }
    )


class TestTheStreamIsTheOnlySourceOfTheModel:
    async def test_the_announced_model_is_reported_not_the_requested_one(self) -> None:
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(_system_line(ANNOUNCED)), MockWorkspace()
        )
        assert result.announced_model == ANNOUNCED
        assert result.announced_model != REQUESTED

    async def test_an_assistant_line_announces_it_too(self) -> None:
        """A recording that begins after the init line still yields an answer;
        claude repeats the model under `message` on every assistant line."""
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(_assistant_line(ANNOUNCED)), MockWorkspace()
        )
        assert result.announced_model == ANNOUNCED

    async def test_the_first_announcement_wins(self) -> None:
        """Last-wins would let anything that ever put another agent's line on
        this stream rebind the identity at the end of the run - the same hazard
        the leader session id capture is first-wins for (#895)."""
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(_system_line(ANNOUNCED), _assistant_line(LATER)),
            MockWorkspace(),
        )
        assert result.announced_model == ANNOUNCED

    async def test_a_codex_stream_announces_nothing(self) -> None:
        """Codex's stream carries no model at all, which is why its cost goes
        unpriced rather than guessed (#788). The requested model must not be
        substituted here: it would report every codex phase as having run a
        claude model, and the pricing precedent says guessing is the worse
        failure.
        """
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(
                json.dumps({"type": "thread.started", "thread_id": "01a04903-c2f9-7de3"}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12}}),
            ),
            MockWorkspace(),
        )
        assert result.announced_model is None

    async def test_an_empty_stream_announces_nothing(self) -> None:
        proc = _make_processor()
        result = await proc.process_stream(_lines_to_stream(), MockWorkspace())
        assert result.announced_model is None

    @pytest.mark.parametrize("blank", ["", "   ", None, 4])
    async def test_a_line_that_says_nothing_usable_is_not_taken(self, blank: object) -> None:
        """A blank or non-string would be recorded as a model that ran, and
        rendering it is how "" ends up looking like a real answer."""
        proc = _make_processor()
        result = await proc.process_stream(_lines_to_stream(_system_line(blank)), MockWorkspace())
        assert result.announced_model is None


def _runtime() -> PhaseRuntime:
    return PhaseRuntime(capture_port=None, session_store=None, writer=None, ledger=None)


def _run(announced_model: str | None) -> AgentExecutionResult:
    return AgentExecutionResult(
        stream_result=StreamResult(
            line_count=1,
            interrupt_requested=False,
            interrupt_reason=None,
            announced_model=announced_model,
        ),
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        command=AgentExecutionCompletedCommand(
            execution_id="exec-1", phase_id="verify", session_id="sess-1"
        ),
    )


class TestTheRuntimeHandsBackWhoRan:
    """The runtime holds the announcement because the stream is gone by the
    time artifacts are collected - the two happen in different handlers.
    """

    def test_the_provider_is_the_caller_s_and_the_model_is_the_stream_s(self) -> None:
        """Two different KINDS of fact in one value: we CHOSE the provider, so
        there is no observation to make; only the stream ever said the model."""
        runtime = _runtime()
        runtime.record_agent_run("verify", execution_id="exec-1", result=_run(ANNOUNCED))
        agent = runtime.agent_for("verify", provider="claude")
        assert (agent.provider, agent.model) == ("claude", ANNOUNCED)

    def test_a_phase_that_announced_nothing_yields_a_provider_and_no_model(self) -> None:
        """The codex case. The provider alone still proves WHICH HARNESS ran,
        which is most of what a cross-model claim needs; the model stays absent
        rather than being filled in from configuration.
        """
        runtime = _runtime()
        runtime.record_agent_run("verify", execution_id="exec-1", result=_run(None))
        agent = runtime.agent_for("verify", provider="codex")
        assert (agent.provider, agent.model) == ("codex", None)

    def test_one_phase_s_announcement_is_not_read_for_another(self) -> None:
        runtime = _runtime()
        runtime.record_agent_run("investigate", execution_id="exec-1", result=_run(ANNOUNCED))
        assert runtime.agent_for("report", provider="claude").model is None

    def test_a_phase_that_never_ran_an_agent_has_no_model(self) -> None:
        assert _runtime().agent_for("verify", provider="claude").model is None


# ── the codex half ───────────────────────────────────────────────────────────

#: What a codex phase actually asks for. `AgentConfiguration.model` defaults to
#: the Claude alias "haiku", and `_is_codex_model` deliberately does not forward
#: it to `codex exec`, so codex runs its ChatGPT-account default instead. That
#: makes this the single most dangerous value in the file: it is in scope at
#: collection time, and recording it would state that a claude model ran the
#: phase whose only job is to be a DIFFERENT model from claude.
REQUESTED_BY_A_CODEX_PHASE = "haiku"
CODEX_ANNOUNCED = "gpt-5.6-sol"
CODEX_LATER = "gpt-5.6-codex"


#: A REAL captured codex rollout: the same on-disk document `transcript_usage`
#: prices a codex delegate from, `turn_context.payload.model` and all. Nothing
#: in this file manufactures a stream that names a model, because no codex
#: version has ever emitted one - a test driven by a shape that does not occur
#: pins nothing, and the one that used to live here (a `thread.started` with a
#: top-level `model`, labelled HYPOTHETICAL in its own docstring) asserted the
#: fallback that matters was never exercised at all.
_ROLLOUT_FIXTURE = _FIXTURES_DIR.parent / "delegation" / "codex_rollout_usage.json"

#: The session `_ROLLOUT_FIXTURE` was captured from, as codex filed it.
CODEX_THREAD_ID = "01a04903-c2f9"


def _real_rollout() -> RolloutDocument:
    document = json.loads(_ROLLOUT_FIXTURE.read_text())
    assert isinstance(document, list)
    # Fail here rather than three assertions later if the capture is ever
    # replaced by one that does not name a model: a fixture that cannot carry
    # the value makes every test below pass for the wrong reason.
    assert any(
        record.get("type") == "turn_context" and record["payload"]["model"] == CODEX_ANNOUNCED
        for record in document
    ), f"{_ROLLOUT_FIXTURE} no longer names {CODEX_ANNOUNCED} on a turn_context"
    return document


class _RolloutOnDisk:
    """A `CodexRolloutPort` serving what codex actually wrote.

    Records the id it was asked for, because "the lookup happened" and "the
    lookup used the id codex announced" are different claims and only the
    second one survives a processor that passes its own platform session id.
    """

    def __init__(self, document: RolloutDocument | None) -> None:
        self._document = document
        self.asked_for: list[str] = []

    async def codex_rollout(self, native_session_id: str) -> RolloutDocument | None:
        self.asked_for.append(native_session_id)
        return self._document


def _codex_thread_started() -> str:
    """The `thread.started` a real codex stream opens with - no model on it."""
    return json.dumps({"type": "thread.started", "thread_id": "01a04903-c2f9"})


def _codex_turn_completed() -> str:
    return json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 3}})


async def _codex_result(
    *lines: str,
    requested: str | None = REQUESTED_BY_A_CODEX_PHASE,
    rollout: _RolloutOnDisk | None = None,
) -> StreamResult:
    proc, _ = _make_codex_processor(_RecordingCollector(), agent_model=requested, rollout=rollout)
    return await proc.process_stream(_lines_to_stream(*lines), MockWorkspace())


class TestTheCodexStreamIsReadTheSameWay:
    """The codex parser is a sibling of the claude one, not a lesser one.

    It used to build its `StreamResult` with no `announced_model` argument at
    all, so the field took the dataclass default. The value that reached the
    artifact was correct and entirely unpinned: nothing here would have noticed
    the requested model being substituted, and no code path would have picked up
    a model if codex started reporting one.

    Then it had the argument and still no value, because it read a top-level
    `model` off the stdout stream and NO CODEX STREAM CARRIES ONE - not the
    golden recording, not any of the ten fixtures. Every codex artifact said
    `provider="codex", model=null`, which proves which harness ran and never
    which model, and codex is always the second model in this platform's
    cross-model reviews. The model it ran is on disk, in the rollout, and these
    are driven by a real one.
    """

    async def test_the_real_recording_names_no_model_on_the_wire(self) -> None:
        """The golden `codex exec --json` capture, unedited, with nobody to ask.

        The stream itself establishes nothing, which is why the rollout read
        below exists. It must not become "haiku", and it must not become the
        string "unknown" either - a sentinel that reads like a model id would
        flow onward as a value, which is the mistake that once priced
        unspecified codex phases as a real model (see `syn_shared/pricing`).
        """
        proc, _ = _make_codex_processor(
            _RecordingCollector(), agent_model=REQUESTED_BY_A_CODEX_PHASE
        )
        result = await proc.process_stream(
            _file_to_stream(_FIXTURES_DIR / "codex_exec_recording.jsonl"), MockWorkspace()
        )
        assert result.announced_model is None
        assert result.announced_model != REQUESTED_BY_A_CODEX_PHASE
        # The run itself worked - this is a stream that reached its terminal
        # turn, not one that died before it could announce anything.
        assert result.error_reason is None

    async def test_the_model_the_rollout_names_is_the_one_reported(self) -> None:
        """The whole point: a real stream that says nothing, a real rollout
        that does, and the rollout's value coming out.

        `gpt-5.6-sol` appears nowhere on the stream and cannot arrive by any
        other route - it is not the requested model, not a default, and not a
        value this test hands to the processor.
        """
        rollout = _RolloutOnDisk(_real_rollout())
        result = await _codex_result(
            _codex_thread_started(), _codex_turn_completed(), rollout=rollout
        )
        assert result.announced_model == CODEX_ANNOUNCED
        assert result.announced_model != REQUESTED_BY_A_CODEX_PHASE

    async def test_the_rollout_is_asked_for_by_the_id_codex_announced(self) -> None:
        """Not the platform's session id, which is `s1` here and which codex
        has never seen. Asking with the wrong id finds another session's
        rollout or none, and both are worse than no answer."""
        rollout = _RolloutOnDisk(_real_rollout())
        await _codex_result(_codex_thread_started(), _codex_turn_completed(), rollout=rollout)
        assert rollout.asked_for == [CODEX_THREAD_ID]

    async def test_a_stream_that_named_a_model_is_not_second_guessed(self) -> None:
        """If codex ever does announce one, the rollout is not consulted at
        all. FIRST wins, the same rule as the leader thread id."""
        rollout = _RolloutOnDisk(_real_rollout())
        proc, _ = _make_codex_processor(
            _RecordingCollector(), agent_model=REQUESTED_BY_A_CODEX_PHASE, rollout=rollout
        )
        result = await proc.process_stream(
            _lines_to_stream(
                json.dumps(
                    {"type": "thread.started", "thread_id": CODEX_THREAD_ID, "model": CODEX_LATER}
                ),
                _codex_turn_completed(),
            ),
            MockWorkspace(),
        )
        assert result.announced_model == CODEX_LATER
        assert rollout.asked_for == []

    async def test_an_unreadable_rollout_leaves_the_model_unknown(self) -> None:
        """Looked, could not read. None, and not the requested model."""
        rollout = _RolloutOnDisk(None)
        result = await _codex_result(
            _codex_thread_started(), _codex_turn_completed(), rollout=rollout
        )
        assert rollout.asked_for == [CODEX_THREAD_ID]
        assert result.announced_model is None

    async def test_a_rollout_that_names_no_model_leaves_it_unknown(self) -> None:
        """Read, and it does not say. The usage-bearing records of the real
        capture with its one `turn_context` removed - a rollout cut off before
        its first turn looks exactly like this."""
        without_model = [r for r in _real_rollout() if r.get("type") != "turn_context"]
        result = await _codex_result(
            _codex_thread_started(),
            _codex_turn_completed(),
            rollout=_RolloutOnDisk(without_model),
        )
        assert result.announced_model is None

    @pytest.mark.parametrize("blank", ["", "   ", None, 4])
    async def test_a_rollout_that_says_nothing_usable_is_not_taken(self, blank: object) -> None:
        """Same rule as the claude side rather than a restatement of it: a
        model that is not a non-blank string names nothing, so `""` must not
        reach an artifact as though it were an id."""
        document = _real_rollout()
        for record in document:
            if record.get("type") == "turn_context":
                record["payload"]["model"] = blank  # type: ignore[index]
        result = await _codex_result(
            _codex_thread_started(), _codex_turn_completed(), rollout=_RolloutOnDisk(document)
        )
        assert result.announced_model is None

    async def test_a_rollout_spanning_two_models_names_neither(self) -> None:
        """The refusal `_codex_usage` already makes for pricing, for the same
        reason: a session that spanned models cannot be attributed to one of
        them, and the later one is not more true for being later."""
        document = [*_real_rollout(), {"type": "turn_context", "payload": {"model": CODEX_LATER}}]
        result = await _codex_result(
            _codex_thread_started(), _codex_turn_completed(), rollout=_RolloutOnDisk(document)
        )
        assert result.announced_model is None

    async def test_nobody_looking_is_not_the_same_as_looking_and_finding_nothing(self) -> None:
        """Both report None, and they must: `None` means "not reported" and no
        other value would be honest. What differs is that one of them ASKED -
        so a processor wired without a source cannot quietly pass for one that
        asked and got nothing."""
        rollout = _RolloutOnDisk(_real_rollout())
        looked = await _codex_result(
            _codex_thread_started(), _codex_turn_completed(), rollout=rollout
        )
        nobody = await _codex_result(_codex_thread_started(), _codex_turn_completed())
        assert looked.announced_model == CODEX_ANNOUNCED
        assert nobody.announced_model is None
        assert rollout.asked_for == [CODEX_THREAD_ID]

    async def test_a_stream_that_never_named_a_session_is_not_matched(self) -> None:
        """No `thread.started`, so no key - and the rollout of whichever
        session happens to be lying around is not this phase's evidence."""
        rollout = _RolloutOnDisk(_real_rollout())
        result = await _codex_result(_codex_turn_completed(), rollout=rollout)
        assert rollout.asked_for == []
        assert result.announced_model is None

    async def test_cli_noise_and_echoed_braces_announce_nothing(self) -> None:
        """A codex phase's stdout carries the agent's own output too (ADR-043),
        so a line that looks like JSON is not evidence of anything."""
        result = await _codex_result(
            "warning: `--full-auto` is deprecated; use `--sandbox workspace-write` instead.",
            '{"model": "not-an-event"',
            _codex_turn_completed(),
        )
        assert result.announced_model is None

    async def test_a_truncated_stream_still_reports_what_the_rollout_says(self) -> None:
        """No terminal turn, so no authoritative usage - but the rollout on
        disk is still there and still says what ran. A phase killed mid-run is
        exactly when a reader most needs to know which model was running."""
        rollout = _RolloutOnDisk(_real_rollout())
        result = await _codex_result(_codex_thread_started(), rollout=rollout)
        assert result.error_reason == MISSING_TERMINAL_TURN_REASON
        assert result.announced_model == CODEX_ANNOUNCED


class _CodexWorkspace:
    """The workspace the handler is given: it streams, and it holds the rollout.

    Both on one object because in production both ARE one object - the rollout
    is a file inside the container the stream came out of, and nothing else can
    still reach it once that container is gone.
    """

    def __init__(self, *lines: str, document: RolloutDocument | None) -> None:
        self._lines = lines
        self._document = document
        self.last_stream_exit_code: int | None = 0
        self.asked_for: list[str] = []

    def stream(self, *_args: object, **_kwargs: object) -> AsyncIterator[str]:
        return _lines_to_stream(*self._lines)

    async def codex_rollout(self, native_session_id: str) -> RolloutDocument | None:
        self.asked_for.append(native_session_id)
        return self._document

    async def interrupt(self) -> bool:
        return True


class TestTheHandlerGivesTheProcessorSomethingToAsk:
    """The wiring hop, which no test on either side of it can see.

    `CodexStreamProcessor` asks whatever it was handed; the handler decides what
    that is. Pass `rollout=None` there - the one-word change that turns this
    whole feature off - and every test above still passes, because they hand
    the processor a source themselves. This runs the real handler.
    """

    async def test_a_codex_phase_reports_the_model_its_rollout_names(self) -> None:
        workspace = _CodexWorkspace(
            _codex_thread_started(),
            _codex_turn_completed(),
            document=_real_rollout(),
        )
        result = await AgentExecutionHandler(controller=None).handle(
            todo=TodoItem(execution_id="exec-1", action=TodoAction.RUN_AGENT, phase_id="verify"),
            workspace=workspace,  # type: ignore[arg-type]
            agent_env={"CODEX_HOME": "/home/agent/.codex"},
            claude_cmd=["codex", "exec", "--json", "verify it"],
            session_id="sess-1",
            agent_model=REQUESTED_BY_A_CODEX_PHASE,
            timeout_seconds=300,
            collector=_RecordingCollector(),
            runner=AgentRunner.CODEX,
        )
        assert workspace.asked_for == [CODEX_THREAD_ID]
        assert result.stream_result.announced_model == CODEX_ANNOUNCED


class TestACodexPhasesArtifactNamesWhoRanIt:
    """The hop that matters: stream -> runtime -> the artifact record.

    Every layer between was already provider-agnostic and already tested with
    `provider="codex"`, so this is the join that was missing - and it is the one
    a test at either end cannot see, because a value dropped at the constructor
    in between satisfies both.
    """

    async def _collect(self, agent: AgentIdentity) -> MockArtifactRepo:
        repo = MockArtifactRepo()
        collector = ArtifactCollector(repo, None, None)
        await collector.collect_from_workspace(
            workspace=CollectedWorkspace(
                collected_files=[("artifacts/output/deliverable.md", b"# Verified")]
            ),  # type: ignore[arg-type]
            workflow_id="w1",
            phase_id="verify",
            execution_id="exec-1",
            session_id="sess-1",
            phase_name="Verify",
            output_artifact_types=("markdown",),
            agent=agent,
        )
        return repo

    async def _agent_after_running(
        self, *lines: str, rollout: _RolloutOnDisk | None = None
    ) -> AgentIdentity:
        runtime = _runtime()
        runtime.record_agent_run(
            "verify",
            execution_id="exec-1",
            result=AgentExecutionResult(
                stream_result=await _codex_result(*lines, rollout=rollout),
                tokens=TokenAccumulator(),
                subagents=SubagentTracker(),
                command=AgentExecutionCompletedCommand(
                    execution_id="exec-1", phase_id="verify", session_id="sess-1"
                ),
            ),
        )
        # `provider` is the phase's own config, exactly as
        # WorkflowExecutionProcessor passes it: we launched the binary.
        return runtime.agent_for("verify", provider="codex")

    async def test_the_model_the_rollout_named_reaches_the_artifact(self) -> None:
        """THE HOP THIS FILE EXISTS FOR, now with a value that can only have
        come from the rollout.

        `gpt-5.6-sol` is read out of a real captured codex rollout, carried
        through the processor, the runtime and the collector, and read back off
        the SAVED artifact record. Every layer in between had to pass it along,
        and a constructor that drops it satisfies a test at either end.
        """
        agent = await self._agent_after_running(
            _codex_thread_started(),
            _codex_turn_completed(),
            rollout=_RolloutOnDisk(_real_rollout()),
        )
        repo = await self._collect(agent)
        assert [a.agent for a in repo.saved] == [
            AgentIdentity(provider="codex", model=CODEX_ANNOUNCED)
        ]

    async def test_a_codex_phase_whose_rollout_was_unreadable_still_names_its_harness(
        self,
    ) -> None:
        """Looked, could not read: the artifact reports the harness and says
        the model is absent rather than guessing it."""
        agent = await self._agent_after_running(
            _codex_thread_started(), _codex_turn_completed(), rollout=_RolloutOnDisk(None)
        )
        repo = await self._collect(agent)
        assert [a.agent for a in repo.saved] == [AgentIdentity(provider="codex", model=None)]

    async def test_a_codex_phase_that_named_nothing_still_names_its_harness(self) -> None:
        """Today's real case, and the one the workflow prompts already handle:
        the artifact proves WHICH HARNESS ran - the cross-model question - and
        reports the model as absent rather than guessed.
        """
        agent = await self._agent_after_running(_codex_thread_started(), _codex_turn_completed())
        repo = await self._collect(agent)
        assert [a.agent for a in repo.saved] == [AgentIdentity(provider="codex", model=None)]


class TestTheProcessorAssemblesTheIdentityItself:
    """The same claim as the class above, DRIVEN instead of reproduced.

    `TestACodexPhasesArtifactNamesWhoRanIt` calls `runtime.agent_for(...)` and
    `ArtifactCollector.collect_from_workspace(...)` itself, in the same order
    and with the same arguments `_handle_collect_artifacts` uses. That makes it
    a COPY of the assembly rather than a run of it, and nothing anywhere makes
    the copy and the original agree. Change the real method to pass
    `provider=None`, to read the model under a different phase id, or to build
    the identity from the phase's config instead of the runtime's observation,
    and every test in that class stays green while every artifact in production
    loses the identity. All three were run as mutations; all three left it
    green, and all three fail here.

    `test_collecting_artifacts_records_the_files_it_collected`
    (test_workflow_execution_processor.py) does call the real method, but swaps
    `ArtifactCollectionHandler` for a `MagicMock` and asserts on the output
    cache, so the `agent=` the method assembles goes to a double that never
    looks at it. It stayed green under all three mutations too.

    So this drives `_handle_collect_artifacts` with the real handler, the real
    collector and a repository that keeps what was saved, and reads
    `AgentIdentity` back off the saved artifact. Both harnesses, for the reason
    given at the top of this file, and because the two halves of the identity
    fail differently on each.
    """

    async def _collected_by_the_processor(
        self, *, ran: StreamResult, agent_config: AgentConfiguration
    ) -> MockArtifactRepo:
        """Hand a finished phase to the processor and let IT collect.

        Everything up to `_handle_collect_artifacts` is production code with
        production wiring: the stream result comes from the real stream
        processor, the runtime is the processor's own, and the collector and
        handler are the ones the method constructs for itself.
        """
        repo = MockArtifactRepo()
        processor = _make_workflow_processor(artifact_repository=repo)
        processor._journal.append = AsyncMock()
        processor._runtimes.of("exec-1").attach_workspace(
            "verify",
            workspace=CollectedWorkspace(
                collected_files=[("artifacts/output/deliverable.md", b"# Verified")]
            ),  # type: ignore[arg-type]
            workspace_cm=AsyncMock(),
            agent_env={},
            claude_cmd=[],
        )
        processor._runtimes.of("exec-1").record_agent_run(
            "verify",
            execution_id="exec-1",
            result=AgentExecutionResult(
                stream_result=ran,
                tokens=TokenAccumulator(),
                subagents=SubagentTracker(),
                command=AgentExecutionCompletedCommand(
                    execution_id="exec-1", phase_id="verify", session_id="sess-1"
                ),
            ),
        )
        await processor._handle_collect_artifacts(
            TodoItem(
                execution_id="exec-1",
                action=TodoAction.COLLECT_ARTIFACTS,
                phase_id="verify",
                session_id="sess-1",
            ),
            ExecutablePhase(
                phase_id="verify",
                name="Verify",
                order=1,
                prompt_template="x",
                agent_config=agent_config,
                output_artifact_types=("markdown",),
            ),
            MagicMock(workflow_id="w1"),
            [],
            PhaseOutputCache(),
        )
        return repo

    async def test_the_processor_stamps_the_model_the_rollout_named(self) -> None:
        """Both halves of the identity, off the artifact the processor saved.

        `gpt-5.6-sol` is not written down in this class. It reaches the artifact
        from the captured rollout through the real codex stream processor, so
        there is no route to this assertion that does not go through the
        assembly under test.
        """
        repo = await self._collected_by_the_processor(
            ran=await _codex_result(
                _codex_thread_started(),
                _codex_turn_completed(),
                rollout=_RolloutOnDisk(_real_rollout()),
            ),
            agent_config=AgentConfiguration(provider="codex"),
        )
        assert [a.agent for a in repo.saved] == [
            AgentIdentity(provider="codex", model=CODEX_ANNOUNCED)
        ]

    async def test_the_processor_does_not_substitute_the_requested_model(self) -> None:
        """A claude phase, because only a claude phase can express the hazard.

        `AgentConfiguration` blanks the model for codex (#788), so on the test
        above `agent_config.model` is already None and a processor reading it
        instead of the runtime would be indistinguishable from one reading
        nothing. Here the phase asked for `claude-sonnet`, its stream announced
        `claude-sonnet-4-5-20250929`, and the two differ - so the value that
        comes out says which of them the processor read.
        """
        assert REQUESTED != ANNOUNCED, "the requested and announced models must differ"
        repo = await self._collected_by_the_processor(
            ran=await _make_processor().process_stream(
                _lines_to_stream(_system_line(ANNOUNCED)), MockWorkspace()
            ),
            agent_config=AgentConfiguration(provider="claude", model=REQUESTED),
        )
        assert [a.agent for a in repo.saved] == [AgentIdentity(provider="claude", model=ANNOUNCED)]

    async def test_a_phase_that_announced_nothing_is_still_stamped_with_its_harness(
        self,
    ) -> None:
        """The case where the model is legitimately absent, which is today's
        real codex case and the one where only the provider carries any
        information at all. An identity dropped here looks exactly like an
        honest "the harness never said" unless the provider is asserted.
        """
        repo = await self._collected_by_the_processor(
            ran=await _codex_result(_codex_thread_started(), _codex_turn_completed()),
            agent_config=AgentConfiguration(provider="codex"),
        )
        assert [a.agent for a in repo.saved] == [AgentIdentity(provider="codex", model=None)]
