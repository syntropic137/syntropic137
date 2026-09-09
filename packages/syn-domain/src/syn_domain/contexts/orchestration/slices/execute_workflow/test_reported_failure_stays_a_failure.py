"""#1256: a phase that reported failure must never be recorded as completed.

The invariant, stated once: WHEN A PHASE RESULT CANNOT BE READ - unparseable,
missing, or overwritten - THE OUTCOME IS FAILURE, NEVER COMPLETION. Absence of
a verdict is not a verdict.

Two production paths defeated it, and they are instances of one shape: a value
that could not be read resolved to something success-like.

  (1) The reader found the report's end with `raw.find("}")`, so the FIRST
      brace in the JSON text ended it - including one inside a string. The
      report below is verbatim from the issue: its `comments` mention
      `dict{}`, the extraction stops mid-string, `json.loads` raises, and the
      handler returned None. `TestTheReportIsReadAsJson` pins that a legal
      string value containing a brace can no longer truncate it.

  (2) The last message each phase said was held under its phase id alone,
      while one processor is shared across concurrent dispatches (see
      `BackgroundWorkflowDispatcher`). Two runs of a workflow share a phase id,
      so the second run's message replaced the first's, and the first then
      read a report that was not its own. `TestTwoExecutionsCannotOverwrite`
      races two runs at the same phase id and shows the second cannot erase
      the first.

  (3) The fix for (1) located the block with `rfind`, so the TEXTUALLY last
      marker won. A report whose own `comments` contain `TASK_RESULT:` was
      therefore read from the mention inside its own string and became
      UNREADABLE - a reported SUCCESS turned into a refusal. Same shape as (1),
      opposite direction: the meaning of the report changed with what its
      strings happened to say. `TestTheMarkerInsideAReportIsNotANewReport`
      pins both directions together, because a fix for either one alone can
      be had by giving up the other.

WHY A PARSER TEST WAS NEVER GOING TO BE ENOUGH. Before this change the parsed
report had NO production consumer: it reached `StreamResult` and stopped there.
So a phase reporting `success: false` completed whether or not the report
parsed, and a test written with brace-free `comments` passed against the broken
state. That is how this survived. The end-to-end proof that the verdict now
decides the outcome lives in
`tests/contexts/workflows/execute_workflow/test_reported_failure_is_not_completion.py`,
which drives `processor.run()`; this file pins the two hops underneath it.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
    VerdictStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_codex_stream_processor import (
    _NoopWorkspace,
    _RecordingCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit

#: The issue's report, verbatim. Its `comments` contain a brace INSIDE the
#: string, which is the whole defect: nothing about this JSON is malformed.
REPORTED_FAILURE = (
    'All done!\n\nTASK_RESULT: {"success": false, '
    '"comments": "the handler returns dict{} not a model"}'
)

#: The same report with the brace removed. It parsed correctly even before
#: this change, so a test written with it proves nothing about #1256 - it is
#: here only as the control that says the two differ in the brace and nothing
#: else.
REPORTED_FAILURE_NO_BRACE = (
    'All done!\n\nTASK_RESULT: {"success": false, "comments": "the handler returns no model"}'
)


class TestTheReportIsReadAsJson:
    """A legal string value must not be able to truncate the report."""

    def test_a_brace_inside_comments_does_not_truncate_the_report(self) -> None:
        verdict = AgentVerdict.from_agent_text(REPORTED_FAILURE)

        assert verdict.status is VerdictStatus.FAILURE
        assert verdict.comments == "the handler returns dict{} not a model", (
            "brace matching stopped at the brace inside the string and lost the report"
        )
        assert verdict.refuses_completion

    def test_the_same_report_without_a_brace_reads_identically(self) -> None:
        assert AgentVerdict.from_agent_text(REPORTED_FAILURE_NO_BRACE).status is (
            VerdictStatus.FAILURE
        )

    def test_nested_objects_are_read_whole(self) -> None:
        text = 'TASK_RESULT: {"success": false, "comments": "x", "detail": {"phase": "verify"}}'

        assert AgentVerdict.from_agent_text(text).status is VerdictStatus.FAILURE

    def test_prose_after_the_report_is_ignored(self) -> None:
        text = 'TASK_RESULT: {"success": true, "comments": "done"}\n\nThanks!'

        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.SUCCESS
        assert not verdict.refuses_completion

    def test_the_last_report_wins(self) -> None:
        """An agent that restates its result has stated it last, not first."""
        text = (
            'TASK_RESULT: {"success": true, "comments": "spoke too soon"}\n'
            'TASK_RESULT: {"success": false, "comments": "the tests fail"}'
        )

        assert AgentVerdict.from_agent_text(text).status is VerdictStatus.FAILURE

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("TASK_RESULT: {not json at all", id="malformed"),
            pytest.param('TASK_RESULT: ["success", false]', id="not-an-object"),
            pytest.param('TASK_RESULT: {"comments": "forgot the verdict"}', id="no-success-key"),
            pytest.param('TASK_RESULT: {"success": "false"}', id="success-is-a-string"),
            pytest.param('TASK_RESULT: {"success": null}', id="success-is-null"),
            pytest.param("TASK_RESULT:", id="marker-with-nothing-after-it"),
        ],
    )
    def test_a_report_that_cannot_be_read_refuses_completion(self, text: str) -> None:
        """UNREADABLE, never SUCCESS. This is the class the two paths belong to."""
        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.UNREADABLE
        assert verdict.refuses_completion

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(None, id="no-message-at-all"),
            pytest.param("", id="empty-message"),
            pytest.param("I have finished the work.", id="prose-with-no-marker"),
        ],
    )
    def test_an_agent_that_never_reported_is_not_a_refusal(self, text: str | None) -> None:
        """The deliberate limit of this change, pinned so a reader can see it.

        Most phases say nothing structured, and treating silence as failure
        would fail every one of them. NOT_REPORTED therefore still completes on
        exit status; what the invariant forbids is a report that EXISTS and
        cannot be read resolving to success.
        """
        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.NOT_REPORTED
        assert not verdict.refuses_completion

    def test_the_refusal_names_the_phase_and_quotes_the_agent(self) -> None:
        """An operator at 2am reads this line, not the stack trace above it."""
        refusal = AgentVerdict.from_agent_text(REPORTED_FAILURE).refusal(phase_id="phase-001")

        assert "phase-001" in refusal
        assert "the handler returns dict{} not a model" in refusal


#: The mirror of `REPORTED_FAILURE`, and just as well-formed: a report whose
#: own `comments` quote the marker. Not exotic - it is what an agent explaining
#: result parsing writes, so the runs most likely to hit it are the runs
#: working on this module.
REPORTED_SUCCESS_QUOTING_THE_MARKER = (
    'TASK_RESULT: {"success": true, "comments": "the parser looks for TASK_RESULT: at the start"}'
)

#: The issue's failure in the spelling the rework asked for. Kept separate from
#: `REPORTED_FAILURE` so the two directions can be asserted side by side.
REPORTED_FAILURE_SHORT = 'TASK_RESULT: {"success": false, "comments": "returns dict{} not a model"}'


class TestTheMarkerInsideAReportIsNotANewReport:
    """Reading a result is robust to the result's own vocabulary.

    Both halves, together, because either one is trivially buyable with the
    other: read the FIRST marker and the success below passes while
    `test_the_last_report_wins` breaks; take the last readable block whatever
    follows it and `test_an_unreadable_final_block_...` breaks. Only a reader
    that knows where each report ENDS satisfies all three.
    """

    def test_a_success_quoting_the_marker_is_still_a_success(self) -> None:
        """The defect: `rfind` read from the quotation inside `comments`."""
        verdict = AgentVerdict.from_agent_text(REPORTED_SUCCESS_QUOTING_THE_MARKER)

        assert verdict.status is VerdictStatus.SUCCESS, (
            "the marker quoted inside comments was read as the start of a new "
            "report, so a reported success became a refusal"
        )
        assert verdict.comments == "the parser looks for TASK_RESULT: at the start", (
            "the verdict was read from somewhere other than the whole block"
        )
        assert not verdict.refuses_completion

    def test_the_reported_failure_still_reads_as_a_failure(self) -> None:
        """The original direction, unchanged. A fix that swaps them is not one."""
        verdict = AgentVerdict.from_agent_text(REPORTED_FAILURE_SHORT)

        assert verdict.status is VerdictStatus.FAILURE
        assert verdict.comments == "returns dict{} not a model"
        assert verdict.refuses_completion

    def test_a_failure_quoting_the_marker_is_still_a_failure(self) -> None:
        """Quoting the marker must not change the verdict in EITHER direction.

        This one refused completion before the fix too - as UNREADABLE rather
        than FAILURE - so it is here for the `comments`, which an operator
        needs and which the truncated read destroyed.
        """
        verdict = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"success": false, "comments": "the TASK_RESULT: block was dropped"}'
        )

        assert verdict.status is VerdictStatus.FAILURE
        assert verdict.comments == "the TASK_RESULT: block was dropped"

    def test_a_later_real_report_still_outvotes_one_that_quotes_the_marker(self) -> None:
        """A quotation is skipped; a genuine second block is not."""
        text = (
            'TASK_RESULT: {"success": true, "comments": "I wrote TASK_RESULT: too early"}\n'
            'TASK_RESULT: {"success": false, "comments": "the tests fail"}'
        )

        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.FAILURE
        assert verdict.comments == "the tests fail"

    def test_an_unreadable_final_block_is_not_rescued_by_an_earlier_success(self) -> None:
        """THE PROPERTY THIS FIX MAY NOT SPEND, pinned against itself.

        Skipping a quotation must not become "take the last block that
        happened to parse". If the agent's FINAL report is malformed, that is
        still a report nobody can read, and it refuses - exactly as it did
        before, and for the same reason absence of a verdict is not a verdict.
        """
        text = 'TASK_RESULT: {"success": true, "comments": "green"}\nTASK_RESULT: {"success": fals'

        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.UNREADABLE, (
            "an earlier readable block was allowed to answer for a later "
            "unreadable one - the fail-closed half, traded away"
        )
        assert verdict.refuses_completion

    def test_a_quoted_marker_in_the_prose_before_the_report_is_skipped(self) -> None:
        """Prose ahead of the block cannot outvote the block."""
        text = (
            "I was asked to explain TASK_RESULT: parsing.\n"
            'TASK_RESULT: {"success": true, "comments": "explained it"}'
        )

        assert AgentVerdict.from_agent_text(text).status is VerdictStatus.SUCCESS

    def test_a_marker_in_prose_AFTER_the_report_still_refuses(self) -> None:
        """THE DELIBERATE LIMIT of this fix, pinned so it is a decision.

        Unchanged behaviour, and it fails closed. What this fix knows is where
        a report ENDS, which is what lets a marker INSIDE one be skipped.
        Text after a block has no such delimiter, so `TASK_RESULT: block as
        instructed` is indistinguishable from a final report that was
        truncated mid-value - and the only way to tell them apart is a rule
        about what "looks like JSON", which would let a bare
        `TASK_RESULT: failed` complete. Refusing here costs a rerun; the
        alternative costs the guarantee.
        """
        text = (
            'TASK_RESULT: {"success": true, "comments": "done"}\n\n'
            "I wrote the TASK_RESULT: block as instructed."
        )

        assert AgentVerdict.from_agent_text(text).status is VerdictStatus.UNREADABLE


class TestTwoExecutionsCannotOverwrite:
    """Two runs racing for the same location; the second cannot erase the first."""

    @staticmethod
    def _run(said: str) -> AgentExecutionResult:
        """A real agent result, built the way the handler builds one."""
        return AgentExecutionResult(
            stream_result=StreamResult(
                line_count=1,
                interrupt_requested=False,
                interrupt_reason=None,
                verdict=AgentVerdict.from_agent_text(said),
                last_agent_message=said,
            ),
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            command=AgentExecutionCompletedCommand(
                execution_id="exec-A", phase_id="implement", session_id="s", exit_code=0
            ),
        )

    def test_the_second_run_does_not_replace_the_first_report(self) -> None:
        runtime = PhaseRuntime(capture_port=None, session_store=None, writer=None, ledger=None)

        runtime.record_agent_run(
            "implement", execution_id="exec-A", result=self._run(REPORTED_FAILURE)
        )
        runtime.record_agent_run(
            "implement",
            execution_id="exec-B",
            result=self._run('TASK_RESULT: {"success": true, "comments": "all green"}'),
        )

        assert runtime.take_last_message("implement", execution_id="exec-A") == REPORTED_FAILURE, (
            "keyed by phase alone, B's success replaced A's failure report"
        )
        assert runtime.take_last_message("implement", execution_id="exec-B") is not None

    def test_a_run_reads_back_its_own_report_under_concurrency(self) -> None:
        """The interleaving the issue describes, driven concurrently.

        Both runs write and then read at the SAME phase id, with an await
        between the two halves so the scheduler can interleave them. Each must
        read back the report it wrote.
        """
        runtime = PhaseRuntime(capture_port=None, session_store=None, writer=None, ledger=None)

        async def one_run(execution_id: str, said: str) -> str | None:
            runtime.record_agent_run("implement", execution_id=execution_id, result=self._run(said))
            await asyncio.sleep(0)  # let the other run write over the top
            return runtime.take_last_message("implement", execution_id=execution_id)

        async def race() -> list[str | None]:
            return await asyncio.gather(
                one_run("exec-A", REPORTED_FAILURE),
                one_run("exec-B", 'TASK_RESULT: {"success": true, "comments": "all green"}'),
            )

        a_read, b_read = asyncio.run(race())

        assert a_read == REPORTED_FAILURE, "A recovered B's success report in place of its failure"
        assert b_read is not None

    def test_taking_a_report_does_not_take_another_execution_s(self) -> None:
        runtime = PhaseRuntime(capture_port=None, session_store=None, writer=None, ledger=None)

        runtime.record_agent_run(
            "implement", execution_id="exec-A", result=self._run(REPORTED_FAILURE)
        )

        assert runtime.take_last_message("implement", execution_id="exec-B") is None, (
            "B read A's report because the key ignored the execution"
        )
        assert runtime.take_last_message("implement", execution_id="exec-A") == REPORTED_FAILURE


class TestBothHarnessesReadTheSameContract:
    """A TASK_RESULT means the same thing whichever CLI produced it."""

    @pytest.mark.asyncio
    async def test_codex_reports_the_same_failure_the_claude_reader_does(self) -> None:
        """Codex used to hard-code no verdict at all, so this report vanished."""

        async def stream() -> AsyncIterator[str]:
            yield json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": REPORTED_FAILURE},
                }
            )

        processor = CodexStreamProcessor(
            tokens=TokenAccumulator(),
            collector=_RecordingCollector(),
            controller=None,
            execution_id="exec-A",
            phase_id="implement",
            session_id="s1",
            agent_model=None,
        )

        result = await processor.process_stream(stream(), _NoopWorkspace())

        assert result.verdict.status is VerdictStatus.FAILURE
        assert result.verdict.comments == "the handler returns dict{} not a model"
