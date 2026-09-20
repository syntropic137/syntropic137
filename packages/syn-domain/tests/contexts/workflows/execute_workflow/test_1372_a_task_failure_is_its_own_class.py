"""#1372: the phase said the TASK was impossible, and the run records that.

THE DEFECT. `FailureClassification` could produce `platform`,
`correct_refusal` and `unclassified`, and nothing else - so a phase that
reported "this cannot be done as written" was recorded as `correct_refusal`,
which is the value an operator reads as THE QUALITY GATE DOING ITS JOB. The
two take opposite actions. A correct refusal is read and closed; an impossible
brief has to be rewritten before anything is re-dispatched, and re-dispatching
it unchanged spends a second whole run arriving back at the same sentence.

WHERE THE EVIDENCE CAME FROM. Nowhere, until #1372 asked for it. Nothing in a
`success=false` report distinguishes the three causes - the comments are prose
and the platform cannot read prose - so the phase now names the cause in
`failure_reason`, one of exactly three words, in the block it already writes.

WHAT THESE DRIVE. The text an agent emits, through the real `VerdictReader`,
the real processor loop, the real aggregate, to
`WorkflowExecutionResult.failure_classification` - the value a caller
dispatching a run reads. Asserting that `FailureClassification.TASK` exists
would prove nothing: the issue's complaint is that nothing could PRODUCE one.

THE SECOND DEFECT, same shape, other target. A phase reporting that the
PLATFORM broke under it was also recorded `correct_refusal` - the system
crediting itself with working on the strength of a report saying it did not.
`failure_reason: "platform"` closes that one, and it is tested here beside the
first because it is the same missing evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration import FailureClassification
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit


def _reports(**fields: str) -> str:
    """A report in the exact shape the prompt hands out, with these fields.

    Built from a mapping rather than written out per case so that every case
    below differs in the one key under test and in nothing else. A hand-written
    fixture per class is how two shapes drift apart and start testing the
    difference between the fixtures.
    """
    keys = ", ".join(f'"{key}": {value}' for key, value in fields.items())
    return f"TASK_RESULT: {{{keys}}}\nTASK_RESULT_END"


#: The three words, and what each must be recorded as. This table IS the
#: contract of #1372 - the prompt hands out exactly these three and the
#: classifier answers exactly these three.
REASON_MEANS = {
    "task": FailureClassification.TASK,
    "platform": FailureClassification.PLATFORM,
    "refused": FailureClassification.CORRECT_REFUSAL,
}


async def _run(says: str, execution_id: str, exit_code: int = 0) -> WorkflowExecutionResult:
    """Run one phase that says exactly this, and hand back what was recorded."""
    fake = (
        FakeAgentExecutionHandler.success(says=says)
        if exit_code == 0
        else FakeAgentExecutionHandler.failed(exit_code=exit_code, says=says)
    )
    return await _make_processor(fake).run(
        workflow_id="wf-1372",
        workflow_name="A phase that names why it failed",
        phases=_one_phase_workflow(),
        inputs={},
        execution_id=execution_id,
    )


async def _classification_of(
    says: str, execution_id: str, exit_code: int = 0
) -> tuple[str, FailureClassification]:
    """The pair every case below asserts on: did it fail, and as what."""
    result = await _run(says, execution_id, exit_code)
    return result.status, result.failure_classification


class TestTheReportedReasonDecidesTheClass:
    """The acceptance criterion, one run per word the prompt offers."""

    @pytest.mark.parametrize(("reason", "expected"), sorted(REASON_MEANS.items()))
    async def test_each_reason_is_recorded_as_the_class_it_names(
        self, reason: str, expected: FailureClassification
    ) -> None:
        status, classification = await _classification_of(
            _reports(success="false", failure_reason=f'"{reason}"', comments='"no"'),
            f"exec-1372-{reason}",
        )

        assert status == "failed", "naming a cause does not stop it being a failure"
        assert classification is expected, (
            f"a phase reporting failure_reason={reason!r} was recorded as "
            f"'{classification}'. The operator deciding whether to re-dispatch "
            f"is reading the wrong answer."
        )

    async def test_the_three_reasons_do_not_collapse_into_one_answer(self) -> None:
        """Three runs differing by ONE key must differ in the record.

        The single-run assertions above would all still hold if two of the
        three mapped to the same class and the third happened to be the one
        asserted - so the property is asserted as a set. This is the state
        #1372 was opened about: three causes, one recorded answer.
        """
        recorded = {
            reason: (
                await _classification_of(
                    _reports(success="false", failure_reason=f'"{reason}"', comments='"no"'),
                    f"exec-1372-set-{reason}",
                )
            )[1]
            for reason in REASON_MEANS
        }

        assert len(set(recorded.values())) == len(REASON_MEANS), (
            f"three different reported causes read as {len(set(recorded.values()))} "
            f"classifications: {recorded}"
        )

    async def test_the_phases_own_words_still_reach_the_operator(self) -> None:
        """Classifying the failure must not swallow the sentence explaining it.

        The class says what to DO; the comments say what happened, and an
        operator rewriting a brief needs the second. A narrower change - one
        that read `failure_reason` in place of the report rather than beside
        it - would show up here and nowhere else.
        """
        result = await _run(
            _reports(
                success="false",
                failure_reason='"task"',
                comments='"the brief names a repo this org does not have"',
            ),
            "exec-1372-comments",
        )

        assert result.error_message is not None
        assert "the brief names a repo this org does not have" in result.error_message


class TestTheFieldCannotCostARunOrInventOne:
    """The field is a label. It may never change WHETHER the run failed.

    A phase that has finished its work and written a valid report must not lose
    it to a typo in a label - which is what a strictly typed `failure_reason`
    would have done: an unknown value failing validation makes the whole block
    UNREADABLE, and #1256 established that an unreadable report refuses the
    phase. A misspelled reason would then cost the run it describes.
    """

    async def test_an_unknown_reason_still_reads_as_a_failure(self) -> None:
        status, classification = await _classification_of(
            _reports(
                success="false",
                failure_reason='"the task was impossible"',
                comments='"see above"',
            ),
            "exec-1372-prose-reason",
        )

        assert status == "failed", (
            "a phase wrote a sentence where a keyword goes and the report "
            "stopped being readable; a label may not cost a run"
        )
        assert classification is FailureClassification.CORRECT_REFUSAL, (
            "an unreadable label must fall back to the pre-#1372 answer, not "
            "to a guess about which word the sentence resembles"
        )

    async def test_a_reason_of_the_wrong_json_type_is_ignored_the_same_way(self) -> None:
        """Not a string at all. The fallback is a property of the FIELD."""
        status, classification = await _classification_of(
            _reports(success="false", failure_reason="47", comments='"see above"'),
            "exec-1372-numeric-reason",
        )

        assert status == "failed"
        assert classification is FailureClassification.CORRECT_REFUSAL

    async def test_a_reason_on_a_successful_report_does_not_manufacture_a_failure(self) -> None:
        """`success: true` decides the outcome; `failure_reason` never does.

        An agent that copies the failure fence's keys onto a success report is
        writing something contradictory, and the contradiction resolves toward
        the outcome field, which is the only one that names an outcome.
        Resolving it the other way would fail finished work over a stray key.
        """
        result = await _run(
            _reports(success="true", failure_reason='"task"', comments='"opened PR #1372"'),
            "exec-1372-reason-on-success",
        )

        assert result.status == "completed"


class TestWhatDidNotChange:
    """The controls. A rule that answers `task` to everything is no rule."""

    async def test_a_report_with_no_reason_is_still_a_correct_refusal(self) -> None:
        """Every run recorded before #1372, and every phase whose prompt
        predates it, wrote exactly this block. Its meaning must not move."""
        status, classification = await _classification_of(
            _reports(success="false", comments='"the fixture repo has no such branch"'),
            "exec-1372-no-reason",
        )

        assert status == "failed"
        assert classification is FailureClassification.CORRECT_REFUSAL

    @pytest.mark.parametrize("reason", sorted(REASON_MEANS))
    async def test_a_killed_run_is_a_platform_failure_whatever_it_claimed(
        self, reason: str
    ) -> None:
        """#1367 outranks this field, and must keep outranking it.

        A phase that reported `failure_reason: "task"` and was then killed by
        its timeout did not establish that the task was impossible - it
        established that the platform ended the run before anyone could know.
        `task` is a claim about work that RAN, so a self-reported cause may
        never survive the death of the run reporting it.
        """
        status, classification = await _classification_of(
            _reports(success="false", failure_reason=f'"{reason}"', comments='"no"'),
            f"exec-1372-killed-{reason}",
            exit_code=124,
        )

        assert status == "failed"
        assert classification is FailureClassification.PLATFORM

    async def test_a_cancelled_run_is_still_unclassified(self) -> None:
        """Cancellation is routed before any verdict is consulted; a reason
        written on the way out changes nothing about that."""
        fake = FakeAgentExecutionHandler(
            interrupt=True,
            says=_reports(success="false", failure_reason='"task"', comments='"no"'),
        )
        result = await _make_processor(fake).run(
            workflow_id="wf-1372",
            workflow_name="A phase that names why it failed",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-1372-cancelled",
        )

        assert result.status == "cancelled"
        assert result.failure_classification is FailureClassification.UNCLASSIFIED


class TestTheStatusAliasCarriesItToo:
    """#1324's deviation shape must not be a hole in #1372's contract.

    A block naming its outcome `status: "failed"` instead of `success: false`
    is read under a documented alias. It is read from the same three-key block
    an agent was handed, so it carries the same `failure_reason` - and a phase
    writing the alias is ALREADY off-contract, which is exactly the population
    most likely to be reporting something impossible.
    """

    @pytest.mark.parametrize(("reason", "expected"), sorted(REASON_MEANS.items()))
    async def test_an_aliased_failure_is_classified_by_its_reason(
        self, reason: str, expected: FailureClassification
    ) -> None:
        status, classification = await _classification_of(
            _reports(status='"failed"', failure_reason=f'"{reason}"', comments='"no"'),
            f"exec-1372-alias-{reason}",
        )

        assert status == "failed"
        assert classification is expected
