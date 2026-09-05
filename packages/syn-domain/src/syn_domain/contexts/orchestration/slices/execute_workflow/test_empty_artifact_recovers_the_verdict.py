"""#1195: an empty artifact must not throw away a verdict that was computed.

THE REPRODUCTION. In `exec-0bac0e1ed2b2` a `verify` phase ran for 9m26s, 60
operations, 1.9M tokens and $1.27, then wrote a zero-byte deliverable.
`CreateArtifactCommand` refused the empty content and the raw Pydantic error -
"String should have at least 1 character [type=string_too_short]" - propagated
out and failed the ENTIRE execution. The verdict was gone and the implement
work that preceded it was left unverified.

WHAT THESE TESTS PIN, and the distinction that is the whole point:

  (a) empty file, agent HAD said something -> the phase succeeds on the
      recovered content, and the record says it was recovered
  (b) empty file, agent said nothing       -> fails, naming the empty artifact
                                              and the phase, in operator words
  (c) (a), (b) and #1167's "produced no output at all" are three states an
      operator can tell apart from outside
  (d) an ordinary non-empty write never enters the fallback at all

(d) is the regression guard. A recovery path that fired on healthy runs would
be a worse bug than the one being fixed, because it would silently rewrite the
deliverables of runs that were working.

The hop tests below (`TestTheVerdictSurvivesEveryHop`) exist because the value
has to cross four boundaries - stream -> StreamResult -> processor ->
collector - and a value dropped at any one of them passes every test that
inspects only the ends.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.artifact_recovery import (
    RECOVERED_TITLE_MARKER,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    EmptyPhaseArtifactError,
    PhaseProducedNoDeclaredOutputError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    MockWorkspace,
    _lines_to_stream,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    _make_processor as _make_event_stream_processor,
)

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        EventStreamProcessor,
    )

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit

#: What the agent said on its stream. Deliberately unlike anything a fixture
#: file contains, so content that reaches the store carrying this string can
#: only have come through the recovery path.
SAID = "VERDICT: the implementation is sound and the gates are green."


def _make_claude() -> EventStreamProcessor:
    """The Claude harness processor, wired exactly as its own suite wires it.

    Reusing that suite's builder rather than repeating the constructor keeps
    this file from silently drifting out of date the next time the processor
    grows a required argument.
    """
    return _make_event_stream_processor()


@dataclass
class _Workspace:
    collected_files: list[tuple[str, bytes]] = field(default_factory=list)

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None: ...

    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
        return self.collected_files


@dataclass
class _Repo:
    saved: list[ArtifactAggregate] = field(default_factory=list)

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, artifact_id: str) -> None:
        return None


async def _collect(
    repo: _Repo,
    files: list[tuple[str, bytes]],
    *,
    last_agent_message: str | None = None,
):
    collector = ArtifactCollector(repo, None, None)
    return await collector.collect_from_workspace(
        workspace=_Workspace(collected_files=files),  # type: ignore[arg-type]
        workflow_id="w1",
        phase_id="verify",
        execution_id="exec-0bac0e1ed2b2",
        session_id="s1",
        phase_name="Verify",
        output_artifact_types=("analysis_report",),
        last_agent_message=last_agent_message,
    )


def _stored(repo: _Repo) -> list[tuple[str, str]]:
    """(title, content) of every artifact that actually reached the store.

    Reads the aggregate's own state rather than the arguments passed in, so a
    value dropped between the command and the aggregate is visible here.
    """
    return [(a.title or "", a.content or "") for a in repo.saved]


class TestAnEmptyArtifactWithSomethingToRecover:
    """(a) The phase succeeds, on content that is marked as recovered."""

    @pytest.mark.asyncio
    async def test_the_verdict_is_stored_instead_of_the_execution_failing(self) -> None:
        repo = _Repo()

        result = await _collect(
            repo,
            [("artifacts/output/deliverable.md", b"")],
            last_agent_message=SAID,
        )

        assert len(result.artifact_ids) == 1, "the phase must produce an artifact, not fail"
        ((title, content),) = _stored(repo)
        assert SAID in content, f"the recovered verdict must be what got stored, got {content!r}"
        assert RECOVERED_TITLE_MARKER in title, (
            f"a recovered artifact must say so in its title, got {title!r}"
        )

    @pytest.mark.asyncio
    async def test_the_recovery_is_not_silent_in_the_content_either(self) -> None:
        """A reader who opens the artifact must not mistake it for the
        deliverable the phase meant to write.

        The title marker serves a listing; the banner serves whoever is
        actually reading the verdict, including the NEXT phase, which receives
        this content as its injected input.
        """
        repo = _Repo()

        result = await _collect(
            repo,
            [("artifacts/output/deliverable.md", b"")],
            last_agent_message=SAID,
        )

        ((_, content),) = _stored(repo)
        assert content.startswith(">"), f"must lead with the provenance banner, got {content!r}"
        assert "#1195" in content
        assert "artifacts/output/deliverable.md" in content, "must name the file that was empty"
        # And it is what the next phase gets injected, not just what is stored.
        assert result.first_content == content

    @pytest.mark.asyncio
    async def test_a_second_non_empty_file_is_untouched_by_its_neighbour(self) -> None:
        """Recovery is per-file. One empty deliverable must not rewrite the
        rest of a phase's output tree."""
        repo = _Repo()

        await _collect(
            repo,
            [
                ("artifacts/output/deliverable.md", b""),
                ("artifacts/output/notes.md", b"# Notes"),
            ],
            last_agent_message=SAID,
        )

        titles_and_contents = _stored(repo)
        assert titles_and_contents[1] == ("Verify: artifacts/output/notes.md", "# Notes")


class TestAnEmptyArtifactWithNothingToRecover:
    """(b) The phase fails, and the failure reads as an incident."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nothing", [None, "", "   \n  "])
    async def test_it_fails_naming_the_empty_artifact_and_the_phase(self, nothing: str | None):
        with pytest.raises(EmptyPhaseArtifactError) as excinfo:
            await _collect(
                _Repo(),
                [("artifacts/output/deliverable.md", b"")],
                last_agent_message=nothing,
            )

        message = str(excinfo.value)
        assert "THE ARTIFACT WAS EMPTY" in message, f"in those words; got {message!r}"
        assert "verify" in message, f"must name the phase, got {message!r}"
        assert "artifacts/output/deliverable.md" in message

    @pytest.mark.asyncio
    async def test_the_operator_never_sees_the_raw_pydantic_error(self) -> None:
        """The exact regression. The reproduction's error_message described a
        schema constraint; an operator had to infer the incident from it."""
        with pytest.raises(EmptyPhaseArtifactError) as excinfo:
            await _collect(_Repo(), [("artifacts/output/deliverable.md", b"")])

        message = str(excinfo.value)
        assert "string_too_short" not in message
        assert "validation error" not in message.lower()
        assert "CreateArtifactCommand" not in message

    @pytest.mark.asyncio
    async def test_the_domain_boundary_still_refuses_empty_content(self) -> None:
        """The rule this fix is NOT allowed to weaken.

        Recovery happens before the command is built. The command's own
        rejection of empty content must remain exactly as strict, or the next
        empty write lands in the store as a stored non-verdict.
        """
        from pydantic import ValidationError

        from syn_domain.contexts.artifacts import CreateArtifactCommand

        with pytest.raises(ValidationError):
            CreateArtifactCommand(
                workflow_id="w1",
                phase_id="verify",
                artifact_type="text",  # type: ignore[arg-type]
                content="",
                title="t",
            )


class TestTheThreeOutcomesAreTellableApart:
    """(c) From outside, using only what an operator or API client can read.

    Before #1195 the first two were one opaque `failed` carrying a Pydantic
    message, which is exactly why the reproduction's root cause was unknowable
    from the API.
    """

    @pytest.mark.asyncio
    async def test_recovered_declares_itself_where_the_api_exposes_it(self) -> None:
        """`phases[].artifact_id` -> `ArtifactDetail.title`, both of which the
        API already serves. No new field, no new endpoint."""
        repo = _Repo()

        await _collect(repo, [("artifacts/output/d.md", b"")], last_agent_message=SAID)

        ((title, _),) = _stored(repo)
        assert RECOVERED_TITLE_MARKER in title

    @pytest.mark.asyncio
    async def test_wrote_nothing_and_wrote_empty_are_different_errors(self) -> None:
        """#1167's case and #1195's case reach `phases[].error_message` with
        messages that do not read alike, and with distinct types."""
        with pytest.raises(PhaseProducedNoDeclaredOutputError) as produced_nothing:
            await _collect(_Repo(), [])
        with pytest.raises(EmptyPhaseArtifactError) as wrote_empty:
            await _collect(_Repo(), [("artifacts/output/d.md", b"")])

        nothing, empty = str(produced_nothing.value), str(wrote_empty.value)
        assert "THE ARTIFACT WAS EMPTY" in empty
        assert "THE ARTIFACT WAS EMPTY" not in nothing, (
            "#1167 is a phase that wrote no file at all - it must keep its own diagnosis"
        )
        assert "produced none" in nothing
        assert not isinstance(produced_nothing.value, EmptyPhaseArtifactError)

    @pytest.mark.asyncio
    async def test_a_phase_that_declared_nothing_is_still_allowed_to_be_silent(self) -> None:
        """The #1167 rule that recovery must not accidentally tighten: a phase
        declaring no output types may legitimately produce none."""
        collector = ArtifactCollector(_Repo(), None, None)

        result = await collector.collect_from_workspace(
            workspace=_Workspace(),  # type: ignore[arg-type]
            workflow_id="w1",
            phase_id="answer",
            execution_id="e1",
            session_id="s1",
            phase_name="Answer",
            output_artifact_types=(),
        )

        assert result.artifact_ids == []


class TestAHealthyRunNeverEntersTheFallback:
    """(d) The regression guard."""

    @pytest.mark.asyncio
    async def test_a_normal_write_is_stored_byte_for_byte(self) -> None:
        """`last_agent_message` is supplied and must be ignored completely:
        no banner, no marker, no substitution, not even a suffix."""
        repo = _Repo()

        result = await _collect(
            repo,
            [("artifacts/output/deliverable.md", b"# Verdict\n\nPASS")],
            last_agent_message=SAID,
        )

        ((title, content),) = _stored(repo)
        assert content == "# Verdict\n\nPASS"
        assert SAID not in content
        assert RECOVERED_TITLE_MARKER not in title
        assert title == "Verify: artifacts/output/deliverable.md"
        assert result.first_content == "# Verdict\n\nPASS"

    @pytest.mark.asyncio
    async def test_a_single_space_is_content_and_is_left_alone(self) -> None:
        """The boundary is the store's own rule - `min_length=1` - and not a
        judgement about whether the content looks useful.

        Whitespace-only content is accepted by `CreateArtifactCommand` today,
        so recovering it here would be this fix substituting a deliverable the
        platform would otherwise have kept. That is out of scope and would be
        the "fires on healthy runs" failure in miniature.
        """
        repo = _Repo()

        await _collect(repo, [("artifacts/output/d.md", b" ")], last_agent_message=SAID)

        ((_, content),) = _stored(repo)
        assert content == " "


class TestTheVerdictSurvivesEveryHop:
    """The transcript has to cross four boundaries to be recoverable at all.

    Each of these pins one hop. Testing only the collector would pass with a
    `StreamResult` field nobody populates, or a processor that reads it and
    forgets to pass it on - which is how this class of bug normally ships.
    """

    @pytest.mark.asyncio
    async def test_claude_keeps_what_the_agent_said_in_its_result_event(self) -> None:
        result = await _make_claude().process_stream(
            _lines_to_stream(json.dumps({"type": "result", "result": SAID, "usage": {}})),
            MockWorkspace(),
        )

        assert result.last_agent_message == SAID

    @pytest.mark.asyncio
    async def test_claude_keeps_the_last_thing_said_when_no_result_event_arrives(self) -> None:
        """The case that matters most: a phase cut off before its terminal
        line is exactly the phase whose file is most likely to be missing."""
        result = await _make_claude().process_stream(
            _lines_to_stream(
                *(
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {"id": text, "content": [{"type": "text", "text": text}]},
                        }
                    )
                    for text in ("Starting the review.", SAID)
                )
            ),
            MockWorkspace(),
        )

        assert result.last_agent_message == SAID, "the LAST message, not the first"

    @pytest.mark.asyncio
    async def test_claude_does_not_offer_a_harness_error_as_the_verdict(self) -> None:
        """An `is_error` result carries the harness's failure text, not the
        agent's conclusion. Recovering it would file a stack trace as a
        verdict, which is worse than failing the phase honestly."""
        result = await _make_claude().process_stream(
            _lines_to_stream(
                json.dumps(
                    {
                        "type": "result",
                        "is_error": True,
                        "result": "API Error: 529 Overloaded",
                        "usage": {},
                    }
                )
            ),
            MockWorkspace(),
        )

        assert result.last_agent_message is None
        assert result.error_reason is not None, "it is still recorded AS an error"

    @pytest.mark.asyncio
    async def test_codex_keeps_its_last_agent_message(self) -> None:
        """The codex harness states its conclusion only in `agent_message`
        items, which the processor previously read and discarded."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
            CodexStreamProcessor,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
            TokenAccumulator,
        )

        fixture = (
            Path(__file__).resolve().parents[6]
            / "tests"
            / "fixtures"
            / "codex"
            / "codex_exec_recording.jsonl"
        )

        collector = MagicMock()
        collector.record_tool_started = AsyncMock()
        collector.record_tool_completed = AsyncMock()
        collector.record_token_usage = AsyncMock()
        collector.record_session_summary = AsyncMock()
        processor = CodexStreamProcessor(
            tokens=TokenAccumulator(),
            collector=collector,
            controller=None,
            execution_id="e1",
            phase_id="verify",
            session_id="s1",
            agent_model="gpt-5.6",
        )

        result = await processor.process_stream(
            _lines_to_stream(*fixture.read_text().splitlines()), MagicMock()
        )

        # The LAST agent_message in the recording, not the first.
        assert result.last_agent_message is not None
        assert result.last_agent_message.startswith("Created `one.txt`")

    @pytest.mark.asyncio
    async def test_the_processor_carries_it_from_the_agent_run_to_collection(self) -> None:
        """The hop with no natural test at either end: `_handle_run_agent`
        remembers it and `_handle_collect_artifacts`, a separate dispatch,
        hands it to the collector."""
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
            TodoAction,
            TodoItem,
        )
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
            ArtifactCollectionResult,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
            PhaseOutputCache,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.test_workflow_execution_processor import (
            _make_processor,
        )

        processor = _make_processor()
        processor._save_and_sync = AsyncMock()
        workspace = MagicMock()
        processor._active_workspaces["verify"] = workspace
        processor._active_envs["verify"] = {}
        processor._active_cmds["verify"] = ["agent"]

        agent_result = MagicMock()
        agent_result.stream_result.last_agent_message = SAID
        agent_result.stream_result.interrupt_requested = False
        agent_result.command.exit_code = 0
        agent_handler = MagicMock()
        agent_handler.handle = AsyncMock(return_value=agent_result)
        processor._agent_handler = agent_handler

        collection_handler = MagicMock()
        collection_handler.handle = AsyncMock(
            return_value=ArtifactCollectionResult(
                artifact_ids=["a1"], first_content="x", command=MagicMock(), files=[]
            )
        )

        run_todo = TodoItem(
            execution_id="exec-0bac0e1ed2b2",
            action=TodoAction.RUN_AGENT,
            phase_id="verify",
            session_id="s1",
        )
        collect_todo = TodoItem(
            execution_id="exec-0bac0e1ed2b2",
            action=TodoAction.COLLECT_ARTIFACTS,
            phase_id="verify",
            session_id="s1",
        )
        phase = ExecutablePhase(
            phase_id="verify", name="Verify", order=1, prompt_template="check it"
        )

        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow"
            ".WorkflowExecutionProcessor.record_phase_conversation",
            new=AsyncMock(),
        ):
            await processor._handle_run_agent(run_todo, phase, MagicMock())
        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow"
            ".WorkflowExecutionProcessor.ArtifactCollectionHandler",
            return_value=collection_handler,
        ):
            await processor._handle_collect_artifacts(
                collect_todo, phase, MagicMock(), [], PhaseOutputCache()
            )

        assert collection_handler.handle.await_args.kwargs["last_agent_message"] == SAID

    @pytest.mark.asyncio
    async def test_the_collection_handler_passes_it_to_the_collector(self) -> None:
        """The last hop. The handler's own signature is where a new keyword is
        most easily accepted and then not forwarded."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
            ArtifactCollectionHandler,
        )

        collector = MagicMock()
        collector.collect_from_workspace = AsyncMock(
            return_value=MagicMock(artifact_ids=[], first_content=None, files=[])
        )
        todo = MagicMock()
        todo.phase_id = "verify"
        todo.execution_id = "exec-0bac0e1ed2b2"

        await ArtifactCollectionHandler(artifact_collector=collector).handle(
            todo=todo,
            workspace=MagicMock(),
            workflow_id="w1",
            session_id="s1",
            phase_name="Verify",
            output_artifact_types=("analysis_report",),
            last_agent_message=SAID,
        )

        kwargs = collector.collect_from_workspace.await_args.kwargs
        assert kwargs["last_agent_message"] == SAID


class TestTheInterruptPathKeepsSalvagingAfterAnEmptyFile:
    """The same empty-file shape on `collect_partial`, which has its own rules.

    Not recovery: an interrupted phase's outcome is already decided by the
    interrupt, and substituting a transcript there would invent a deliverable
    for a run nobody reads as one. What is fixed is that the store's refusal
    used to escape into `collect_partial`'s blanket `except` and abandon every
    REMAINING file, so one empty file cost the whole salvage.
    """

    @pytest.mark.asyncio
    async def test_one_empty_file_no_longer_discards_the_rest(self) -> None:
        repo = _Repo()
        collector = ArtifactCollector(repo, None, None)

        ids = await collector.collect_partial(
            workspace=_Workspace(  # type: ignore[arg-type]
                collected_files=[
                    ("artifacts/output/empty.md", b""),
                    ("artifacts/output/kept.md", b"salvageable work"),
                ]
            ),
            workflow_id="w1",
            phase_id="verify",
            execution_id="e1",
            session_id="s1",
            phase_name="Verify",
            output_artifact_types=("markdown",),
        )

        assert len(ids) == 1, "the file after the empty one must still be salvaged"
        assert [c for _, c in _stored(repo)] == ["salvageable work"]
