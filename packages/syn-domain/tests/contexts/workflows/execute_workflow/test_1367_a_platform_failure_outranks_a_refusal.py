"""#1367: a kill is not a correct refusal, however the run reported itself.

THE DEFECT, and why it hid inside the fix for #1256. The processor asked the
phase's own verdict first and raised on it, and only THEN looked at how the
process had died. Every one of those raises carried
`FailureClassification.CORRECT_REFUSAL`, because a refusal is what the verdict
says it is. So a run that wrote a perfectly readable ``success=false`` report
and was then killed - by its timeout, by a signal, by the OOM killer, by an
ordinary non-zero exit, or by the handler forcing a broken codex stream to
exit 1 - was recorded as THE QUALITY GATE DOING ITS JOB.

That is the one direction this field must never be wrong in. `correct_refusal`
is what an operator reads as "the platform is fine, the work was judged not
deliverable"; counting timeouts and OOM kills as that hides exactly the
outages #1357 added the field to surface, and hides them behind a number that
looks healthy.

These drive the whole `run()` loop and assert on
``WorkflowExecutionResult.failure_classification`` - the value a caller
dispatching a run synchronously actually reads - rather than on what
`AgentVerdict` returns. A verdict that answers `CORRECT_REFUSAL` while the
recorded run says `platform` is fine; the reverse is the defect, and only the
recorded end of the hop can tell them apart.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration import FailureClassification
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor, _one_phase_workflow

pytestmark = pytest.mark.unit

#: A report nothing can quarrel with: delimited, closed, valid JSON, a JSON
#: boolean in ``success``. Every case below pairs THIS with a platform fault,
#: so the only thing separating them from a correct refusal is the fault.
VALID_REFUSAL = (
    'TASK_RESULT: {"success": false, "comments": "the fixture repo has no such branch"}\n'
    "TASK_RESULT_END"
)

#: How each run died. The exit codes are the real ones an operator meets:
#: `timeout(1)` sends 124, a shell reports a signal death as 128+n, python's
#: `Popen` reports it as -n, the OOM killer shows up as 137, and 1 is every
#: ordinary CLI failure. All five arrive at the same place.
PLATFORM_DEATHS = [
    pytest.param(124, id="timeout"),
    pytest.param(-11, id="sigsegv-as-negative"),
    pytest.param(139, id="sigsegv-as-128-plus-n"),
    pytest.param(137, id="oom-kill"),
    pytest.param(1, id="ordinary-cli-failure"),
]


class TestAKilledRunIsAPlatformFailure:
    """The run refused itself and then died. The death is what is recorded."""

    @pytest.mark.parametrize("exit_code", PLATFORM_DEATHS)
    async def test_a_valid_refusal_does_not_survive_a_non_zero_exit(self, exit_code: int) -> None:
        fake = FakeAgentExecutionHandler.failed(exit_code=exit_code, says=VALID_REFUSAL)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1367",
            workflow_name="Refused and then killed",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id=f"exec-1367-exit{exit_code}",
        )

        assert result.status == "failed"
        assert result.failure_classification is FailureClassification.PLATFORM, (
            f"exit {exit_code} with a valid success=false report was recorded as "
            f"'{result.failure_classification}'. A run the platform killed is "
            "being counted as the quality gate working."
        )

    @pytest.mark.parametrize("exit_code", PLATFORM_DEATHS)
    async def test_the_operator_still_reads_what_the_phase_said(self, exit_code: int) -> None:
        """Reclassifying it must not throw the phase's own report away.

        The classification changes who is to blame; it does not change what
        happened, and an operator debugging a 124 wants both. This is the
        regression that a narrower fix - just moving the exit-code check above
        the verdict - would have caused silently.
        """
        fake = FakeAgentExecutionHandler.failed(exit_code=exit_code, says=VALID_REFUSAL)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1367",
            workflow_name="Refused and then killed",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id=f"exec-1367-reason-exit{exit_code}",
        )

        assert result.error_message is not None
        assert f"exit_code={exit_code}" in result.error_message
        assert "the fixture repo has no such branch" in result.error_message

    async def test_a_broken_stream_costs_a_refusal_its_badge_too(self) -> None:
        """The codex shape, at the exit code the handler leaves behind.

        `AgentExecutionHandler` forces a broken codex stream to exit 1, so this
        is covered by the matrix above - but the stream fault is the evidence
        and the exit code is only how it reaches here. Pinned separately so a
        handler that stops forcing the exit code cannot quietly restore
        `correct_refusal` for a run whose telemetry is broken.
        """
        fake = FakeAgentExecutionHandler.success(
            says=VALID_REFUSAL, stream_error="Malformed JSON on line 41"
        )
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1367",
            workflow_name="Refused on a broken stream",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1367-broken-stream",
        )

        assert result.status == "failed"
        assert result.failure_classification is FailureClassification.PLATFORM


class TestWhatMustStillBeACorrectRefusal:
    """The control. A rule that classifies everything as platform is no rule."""

    async def test_a_valid_refusal_on_a_clean_exit_is_a_correct_refusal(self) -> None:
        """Exit 0, nothing wrong with the stream, nobody cancelled: the ONLY
        thing that ended this run is the phase's own judgement, which is what
        `correct_refusal` means."""
        fake = FakeAgentExecutionHandler.success(says=VALID_REFUSAL)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1367",
            workflow_name="Refused cleanly",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1367-clean",
        )

        assert result.status == "failed"
        assert result.failure_classification is FailureClassification.CORRECT_REFUSAL

    async def test_an_ordinary_timeout_is_still_a_platform_failure(self) -> None:
        """The other control: a run that made no claim at all and was killed
        was already `platform`, and must stay `platform`. A fix that moved the
        classification would show up here as a change to a case it never
        touched."""
        fake = FakeAgentExecutionHandler.failed(exit_code=124, says="Still working on it")
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1367",
            workflow_name="Killed with no report",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1367-silent-timeout",
        )

        assert result.status == "failed"
        assert result.failure_classification is FailureClassification.PLATFORM

    async def test_a_clean_run_that_claimed_nothing_still_completes(self) -> None:
        """A stream fault only demotes a refusal; it never invents a failure.

        #1111: a codex stream that stops before `turn.completed` having
        produced the deliverable is a telemetry gap, and failing it discards
        finished work and skips every downstream phase. So a broken stream on
        an exit-0 run with no refusal completes, exactly as before.
        """
        fake = FakeAgentExecutionHandler.success(
            says="Opened PR #1367", stream_error="Stream ended without turn.completed"
        )
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1367",
            workflow_name="Broken stream over finished work",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1367-telemetry-gap",
        )

        assert result.status == "completed"

    async def test_a_cancel_is_never_classified_at_all(self) -> None:
        """Cancellation is the fourth term in the conjunction, and it is held
        one frame up: the processor routes an interrupt before any of this is
        asked. Pinned here because `_ran_cleanly` names it too, and a reader
        who sees it in both places should find a test saying which one wins."""
        fake = FakeAgentExecutionHandler(interrupt=True, says=VALID_REFUSAL)
        processor = _make_processor(fake)

        result = await processor.run(
            workflow_id="wf-1367",
            workflow_name="Cancelled mid-refusal",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1367-cancelled",
        )

        assert result.status == "cancelled"
        assert result.failure_classification is FailureClassification.UNCLASSIFIED
