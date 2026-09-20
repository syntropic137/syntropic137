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

THEN #1392 MOVED WHERE THAT EVIDENCE LANDS, and these tests moved with it. The
word is the AGENT'S, and the only thing corroborating it is that the process
exited cleanly - evidence about the harness, not about whether the task was
possible. So a run naming itself `task` was deciding which platform failure
number it appeared in, on its own say-so. The word still travels the whole way
to the operator, under a name that says what it is
(`reported_failure_reason`); what changed is that it no longer decides
`failure_classification`, which is what the numbers are computed from. The
tests below therefore assert the two SEPARATELY, and the separation is the
point: the four causes stay four in what was said, and the measurement moves
only for the one word that withdraws a claim.

THE SECOND HALF OF #1392 IS `TestWhatCouldNotTellIsNotSilence`. The prompt had
long told agents to omit the key when none of the words was honest, promising
the omission would read as "could not tell"; it read as `CORRECT_REFUSAL`,
which says the system worked. `unknown` is the word that says it instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from syn_domain.contexts.orchestration import FailureClassification
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ReportedFailureReason,
)
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


class _Recorded(NamedTuple):
    """What a run records about a failure: the word, and the measurement.

    Two fields rather than one because #1392 established that they are two
    different kinds of fact, and a test that reads only one of them cannot
    tell a report from a finding (see the module docstring).
    """

    reports: ReportedFailureReason
    classifies_as: FailureClassification


#: The four words, and the whole of what each must be recorded as. This table
#: IS the contract: the prompt hands out exactly these four and the reader
#: answers exactly these four.
#:
#: READ THE COLUMNS AGAINST EACH OTHER - that is what #1392 changed. All four
#: `reports` differ; three of the four `classifies_as` are the same. The word
#: an agent chose always reaches the operator, and it moves the platform's own
#: measurement only for `unknown`, which takes a claim AWAY. Putting `task`
#: back in the right-hand column would look like a richer contract and would be
#: the defect #1392 closed.
REASON_MEANS: dict[str, _Recorded] = {
    "task": _Recorded(ReportedFailureReason.TASK, FailureClassification.CORRECT_REFUSAL),
    "platform": _Recorded(ReportedFailureReason.PLATFORM, FailureClassification.CORRECT_REFUSAL),
    "refused": _Recorded(ReportedFailureReason.REFUSED, FailureClassification.CORRECT_REFUSAL),
    "unknown": _Recorded(ReportedFailureReason.UNKNOWN, FailureClassification.UNCLASSIFIED),
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


async def _recorded_by(says: str, execution_id: str, exit_code: int = 0) -> _Recorded:
    """Both halves of the record, for the cases that must not confuse them.

    Read off the same `WorkflowExecutionResult` a caller dispatching a run
    synchronously reads, so a hop that carries the classification and drops the
    reported word fails here rather than passing on the half it kept.
    """
    result = await _run(says, execution_id, exit_code)
    assert result.reported_failure_reason is not None, (
        f"the run recorded no reported reason at all, so there is nothing here "
        f"to tell apart from a phase that named none: {result.status}"
    )
    return _Recorded(result.reported_failure_reason, result.failure_classification)


class TestTheReportedReasonDecidesTheClass:
    """The acceptance criterion, one run per word the prompt offers."""

    @pytest.mark.parametrize(("reason", "expected"), sorted(REASON_MEANS.items()))
    async def test_each_reason_is_recorded_as_the_word_it_wrote(
        self, reason: str, expected: _Recorded
    ) -> None:
        result = await _run(
            _reports(success="false", failure_reason=f'"{reason}"', comments='"no"'),
            f"exec-1372-{reason}",
        )

        assert result.status == "failed", "naming a cause does not stop it being a failure"
        assert result.reported_failure_reason is expected.reports, (
            f"a phase reporting failure_reason={reason!r} reached the caller "
            f"reporting {result.reported_failure_reason!r}. The operator asking "
            f"what the agent said is reading the wrong answer."
        )
        assert result.failure_classification is expected.classifies_as, (
            f"a phase reporting failure_reason={reason!r} was measured as "
            f"'{result.failure_classification}', and a word an agent chose may "
            f"only ever WITHDRAW a claim from that number (#1392)."
        )

    async def test_the_four_reasons_do_not_collapse_into_one_record(self) -> None:
        """Four runs differing by ONE key must differ in the record.

        The single-run assertions above would all still hold if two of the four
        mapped to the same word and the third happened to be the one asserted -
        so the property is asserted as a set. This is the state #1372 was opened
        about: several causes, one recorded answer.

        IT IS ASSERTED ON THE REPORTED WORD, not on the classification, and that
        is the whole of what #1392 moved. Four causes still reach four different
        people; they do it through what the agent SAID, because what the
        platform MEASURED is the same for three of them and is not the agent's
        to vary.
        """
        recorded = {
            reason: (
                await _recorded_by(
                    _reports(success="false", failure_reason=f'"{reason}"', comments='"no"'),
                    f"exec-1372-set-{reason}",
                )
            ).reports
            for reason in REASON_MEANS
        }

        assert len(set(recorded.values())) == len(REASON_MEANS), (
            f"{len(REASON_MEANS)} different reported causes read as "
            f"{len(set(recorded.values()))} words: {recorded}"
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


class TestWhatCouldNotTellIsNotSilence:
    """#1392: the prompt promised a way to say "I could not tell". Here it is.

    THE DEFECT, WHICH WAS A PROMISE AND NOT A CRASH. The prompt told agents to
    leave `failure_reason` out when none of the words was honest, and said the
    omission would be read as "could not tell". It could not be. An absent key
    is also what every phase wrote before the key existed, so absence resolves
    to `None` and `None` resolves to `CORRECT_REFUSAL` - the value that says
    THE SYSTEM WORKED, which is the opposite of "nobody knows". An agent that
    followed the instruction honestly produced the one answer it did not mean,
    and nothing anywhere failed.

    WHY THE TWO CASES ARE ASSERTED AGAINST EACH OTHER rather than one per test.
    Either assertion alone is satisfiable by a mistake: make absence
    `UNCLASSIFIED` too and the `unknown` case passes while every failure
    recorded before this key existed silently changes meaning; leave `unknown`
    unread and the absence case passes while the prompt still promises
    something nothing delivers. The contract is the DIFFERENCE between them, so
    the difference is what is asserted, from two runs that differ in exactly
    one key.
    """

    async def test_a_phase_that_could_not_tell_is_recorded_as_nobody_knowing(self) -> None:
        """The word `unknown` reaches a genuinely unclassified record.

        `UNCLASSIFIED` on a run that FAILED with a readable report is a state
        nothing could previously produce - a readable `success=false` was
        always `CORRECT_REFUSAL` - which is why `status` is asserted beside it.
        Without that, a cancelled run or a row written before #1357 would
        satisfy this test having established nothing.
        """
        result = await _run(
            _reports(
                success="false",
                failure_reason='"unknown"',
                comments='"the push failed and I could not tell whether the token or the branch was wrong"',
            ),
            "exec-1392-unknown",
        )

        assert result.status == "failed"
        assert result.reported_failure_reason is ReportedFailureReason.UNKNOWN, (
            "the agent wrote the one word the prompt offers for 'I could not "
            "tell' and the record does not show it saying so"
        )
        assert result.failure_classification is FailureClassification.UNCLASSIFIED, (
            f"a phase that reported it could not classify its own failure was "
            f"recorded as '{result.failure_classification}'. An operator reads "
            f"that as a question already answered."
        )

    async def test_saying_nothing_still_means_what_it_meant_before_the_key_existed(
        self,
    ) -> None:
        """The other half, and the reason `unknown` had to be a WORD.

        Every report in the store was written without this key. Reading those
        bytes as "nobody knows" would be a new claim about history rather than
        a fix, so absence keeps the answer it has always had.
        """
        result = await _run(
            _reports(success="false", comments='"the fixture repo has no such branch"'),
            "exec-1392-absent",
        )

        assert result.status == "failed"
        assert result.reported_failure_reason is None, (
            "a phase that named no reason is recorded as having named one"
        )
        assert result.failure_classification is FailureClassification.CORRECT_REFUSAL, (
            "the meaning of a report written before #1372 moved, so every "
            "failure already in the store now reads as something else"
        )

    async def test_the_two_do_not_read_alike(self) -> None:
        """Two runs differing in exactly one key must differ in the record.

        This is the acceptance criterion of #1392's second finding, and the
        only assertion here that both halves above cannot be made to pass
        without: it fails if absence and `unknown` are folded into either
        answer, in either direction.
        """
        could_not_tell = await _run(
            _reports(success="false", failure_reason='"unknown"', comments='"no"'),
            "exec-1392-pair-unknown",
        )
        said_nothing = await _run(
            _reports(success="false", comments='"no"'),
            "exec-1392-pair-absent",
        )

        assert could_not_tell.failure_classification is not said_nothing.failure_classification, (
            f"a phase that SAID it could not tell and a phase that said nothing "
            f"are both recorded as "
            f"'{could_not_tell.failure_classification}'; the prompt offers a "
            f"word that changes nothing"
        )


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

    @pytest.mark.parametrize(
        ("label", "written"),
        [
            ("a number", "47"),
            ("a null", "null"),
            ("a boolean", "true"),
            ("an object", '{"kind": "task"}'),
            ("an array", '["task"]'),
        ],
    )
    async def test_a_reason_of_the_wrong_json_type_is_ignored_the_same_way(
        self, label: str, written: str
    ) -> None:
        """Not a string at all. The fallback is a property of the FIELD.

        EVERY JSON TYPE, because the narrowing is what makes a typo survivable
        and a narrowing that covers four types out of six is a crash waiting
        for the fifth. The object and the array are the ones worth naming: they
        are UNHASHABLE, so a lookup written the obvious way raises `TypeError`
        rather than the `ValueError` the reader catches, and the failure path
        would die reading a label on a failure it had already decided.

        Running through the real processor is itself the no-throw assertion - a
        reader that raised would not reach any assertion below - and the
        documented fallback is asserted beside it so that "did not crash" is
        not mistaken for "was read".
        """
        status, classification = await _classification_of(
            _reports(success="false", failure_reason=written, comments='"see above"'),
            f"exec-1372-wrongtype-{label.replace(' ', '-')}",
        )

        assert status == "failed", f"{label} where a keyword goes cost the run its report"
        assert classification is FailureClassification.CORRECT_REFUSAL, (
            f"{label} in `failure_reason` was resolved to "
            f"'{classification}' rather than to the documented fallback for a "
            f"reason nobody can read"
        )

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
    async def test_an_aliased_failure_carries_its_reason_the_same_way(
        self, reason: str, expected: _Recorded
    ) -> None:
        result = await _run(
            _reports(status='"failed"', failure_reason=f'"{reason}"', comments='"no"'),
            f"exec-1372-alias-{reason}",
        )

        assert result.status == "failed"
        assert result.reported_failure_reason is expected.reports
        assert result.failure_classification is expected.classifies_as
