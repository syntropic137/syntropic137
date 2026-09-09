"""#1256: a phase that reports failure must not be recorded as completed.

THE REPRODUCTION, verbatim from the issue::

    TASK_RESULT: {"success": false, "comments": "the handler returns dict{} not a model"}

Run against `main` this whole file is green in the wrong direction: every one
of these executions came back ``completed``. Two independent defects produced
that, and the second is why the first was never noticed:

  1. the block was located by scanning forward to the first ``}``, so the brace
     inside ``dict{}`` truncated the JSON mid-string and the decode error was
     swallowed into ``None``;
  2. nothing downstream read the parsed result anyway. It reached
     ``StreamResult.agent_task_result`` and stopped there, so a perfectly
     parsed ``success: false`` completed the phase just the same.

`test_a_failure_report_without_a_brace_also_fails` is the control that shows
(2) on its own, and it is exactly how this survived: a reproduction written
with a brace-free ``comments`` string exercises a clean parse and STILL passes
against the broken code, because the parse was never the only thing wrong.

These drive the whole `run()` loop rather than the parser, because the claim
being made is about a RECORDED OUTCOME - `result.status` and whether the next
phase ran - not about what a helper returns.
"""

from __future__ import annotations

import pytest

from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor, _one_phase_workflow, _two_phase_workflow

#: The issue's own reproduction. The brace inside the string is the point.
REPORTED_FAILURE = (
    'All done? No. TASK_RESULT: {"success": false, '
    '"comments": "the handler returns dict{} not a model"}'
)

pytestmark = pytest.mark.unit


class TestAReportedFailureIsNotACompletion:
    """The verdict the agent wrote is the outcome the execution records."""

    async def test_a_failure_report_containing_a_brace_fails_the_execution(self) -> None:
        """The issue's reproduction, end to end.

        Exit code 0 and a workspace that produced nothing wrong: the ONLY
        thing saying this phase failed is the phase itself.
        """
        fake = FakeAgentExecutionHandler.success(says=REPORTED_FAILURE)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Reported failure",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-brace",
        )

        assert result.status == "failed", (
            f"Expected 'failed' but got '{result.status}'. A phase that wrote "
            "success:false was recorded as completed - the report was read and "
            "then discarded."
        )

    async def test_the_recorded_reason_quotes_what_the_agent_said(self) -> None:
        """An operator must be able to see WHY without opening the transcript.

        The comments string is the half that the brace-matching parse used to
        truncate, so its presence here is also evidence the whole value
        survived the parse rather than just its first eight characters.
        """
        fake = FakeAgentExecutionHandler.success(says=REPORTED_FAILURE)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Reported failure",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-reason",
        )

        assert result.error_message is not None
        assert "the handler returns dict{} not a model" in result.error_message
        assert "phase-001" in result.error_message

    async def test_a_failure_report_without_a_brace_also_fails(self) -> None:
        """THE CONTROL. This same claim, with nothing to defeat the parser.

        On `main` this parses cleanly and the execution still completes,
        because the parsed verdict had no consumer. A reproduction written
        this way therefore proves the phase completes and proves nothing about
        why - which is how the brace path stayed hidden underneath it.
        """
        fake = FakeAgentExecutionHandler.success(
            says='TASK_RESULT: {"success": false, "comments": "the handler returns no model"}'
        )
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Reported failure",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-nobrace",
        )

        assert result.status == "failed"

    async def test_the_next_phase_does_not_run_after_a_reported_failure(self) -> None:
        """The consequence that matters. When the phase reporting failure is
        `verify`, an execution that carries on has removed its own gate - the
        exact shape #1167 was, arriving by a different route."""
        fake = FakeAgentExecutionHandler.success(says=REPORTED_FAILURE)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Reported failure then downstream",
            phases=_two_phase_workflow(first_declares=()),
            inputs={},
            execution_id="exec-1256-downstream",
        )

        assert result.status == "failed"
        assert fake.call_count == 1, (
            "The downstream phase ran anyway: a reported failure stopped nothing."
        )

    async def test_an_unreadable_report_fails_rather_than_completing(self) -> None:
        """Absence of a verdict is not a verdict. A block that cannot be read
        may be a failure report, and completing on it is the direction that
        lets defects through."""
        fake = FakeAgentExecutionHandler.success(
            says='TASK_RESULT: {"success": fals, "comments": "cut off mid-word'
        )
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Unreadable report",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-unreadable",
        )

        assert result.status == "failed"
        assert result.error_message is not None
        assert "could not be read" in result.error_message


class TestWhatMustStillComplete:
    """The regression guards. A gate that fails everything is not a gate."""

    async def test_a_reported_success_completes(self) -> None:
        fake = FakeAgentExecutionHandler.success(
            says='Finished. TASK_RESULT: {"success": true, "comments": "opened PR #1257"}'
        )
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Reported success",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-success",
        )

        assert result.status == "completed"

    async def test_a_success_that_quotes_the_marker_completes(self) -> None:
        """The mirror defect, at the hop that RECORDS the outcome.

        `rfind` read this report from the `TASK_RESULT:` quoted inside its own
        `comments`, so the block decoded to nothing and the execution was
        recorded FAILED on a phase that reported success. An agent explaining
        result parsing writes exactly this sentence, which is why it fired
        hardest on the runs working on #1256 itself.

        Asserted on `result.status` rather than on the verdict, because a
        parser that returns SUCCESS while the execution still records `failed`
        is the shape (2) above already got away with once.
        """
        fake = FakeAgentExecutionHandler.success(
            says=(
                'TASK_RESULT: {"success": true, "comments": '
                '"the parser looks for TASK_RESULT: at the start"}'
            )
        )
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Reported success quoting the marker",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-quotes-marker",
        )

        assert result.status == "completed", (
            f"Expected 'completed' but got '{result.status}'. A phase that "
            "reported success was failed because its comments mentioned the "
            "marker."
        )
        assert result.error_message is None

    async def test_a_phase_that_reported_nothing_still_completes(self) -> None:
        """THE DELIBERATE LIMIT, pinned so a change to it is a decision.

        Silence is not a verdict either, but it is a different fact from an
        unreadable one: the agent made no claim, and one harness has no claim
        to make. Failing on silence is a change to what the platform REQUIRES
        of every agent, not a fix to a report being discarded, and it would
        land first on the phases that never had a report to lose. Such a
        phase is still governed by its exit status, its declared outputs
        (#1167) and its artifact content (#1195).
        """
        fake = FakeAgentExecutionHandler.success(says="I finished the work.")
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="No report at all",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-silent",
        )

        assert result.status == "completed"

    async def test_a_cancel_is_still_a_cancel_not_a_reported_failure(self) -> None:
        """Order matters: the interrupt path returns before the verdict is
        consulted, so a run stopped by an operator is not relabelled as a
        phase that failed on its own report (#918)."""
        fake = FakeAgentExecutionHandler(interrupt=True, says=REPORTED_FAILURE)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1256",
            workflow_name="Cancelled mid-report",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1256-cancel",
        )

        assert result.status == "cancelled"
