"""#1324: the one result shape agents write instead of the contract, and no more.

THE FAILURE. exec-cd5e75eaeb63 ran `implement`, pushed commit 7e96e27c, opened
PR #1371 - and then reported itself with a schema of its own invention:
``{"status": "completed", "branch": ..., "commit": ..., "pr": 1371}``. There is
no ``success`` key in that, so `phase_verdict` read UNREADABLE, the phase was
refused, and $10.76 of finished work ended the run. It happened AFTER #1327 made
the prompt's fences literal and copyable, which is what makes it a separate
shape rather than the same one again: the fences are now correct and this agent
never looked at them. Every failing block observed since has the same one
defect, the key spelled ``status``.

WHAT IS PINNED HERE, in two halves that have to be read together:

  - the alias READS that shape - ``completed`` is a success, ``failed`` is a
    failure - so a phase that finished is not failed over the name of a key;
  - the alias is CLOSED, and the negative rows are the actual subject of this
    module. `_StatusAlias` has two members and matching is exact, so
    ``Completed``, ``done``, a bare `true` and a trailing space are all
    UNREADABLE exactly as they were before the alias existed.

THE ROW THAT MATTERS MOST is
``{"status": "completed", "success": "true"}``. The contract model refuses that
``success`` because a STRING IS NOT A BOOLEAN - the coercion `phase_verdict`
exists to refuse, since ``"true"`` is equally the start of ``"true, but the
tests fail"``. If the alias then read the block off its ``status``, the strict
refusal would be undone one line later and a malformed report would COMPLETE a
phase. It is refused here instead: an alias may read a block that says nothing
about ``success``, never one that says something unreadable about it.

MUTATION RECORD (each row was shown red before being kept):

  - adding ``COMPLETED_CAPITALISED = "Completed"`` to `_StatusAlias`, or
    lowercasing the value before the lookup, fails the negative rows;
  - deleting `_StatusAliasResult._refuse_a_block_that_also_wrote_success` fails
    the ``success``-beside-``status`` row above;
  - reading the alias BEFORE the contract, or weighing the two keys against
    each other at all, fails the ``status``-beside-``success`` matrix;
  - decoding with a plain `json.JSONDecoder()` - the reading before duplicate
    members were noticed - fails every repeated-``status`` row;
  - accumulating the repeat across `_decode_payload`'s hook calls rather than
    overwriting it - ``repeated = repeated or ...`` - fails the nested row,
    and moving the repeat guard ahead of the contract fails the rows where a
    repeat sits beside a written ``success``;
  - returning ``cls(VerdictStatus.UNREADABLE, ...)`` from `_from_report` as it
    did before fails every positive row;
  - dropping ``via_status_alias=True`` fails the refusal-wording test;
  - deleting the ``logger.warning`` fails the visibility test;
  - reverting the prompt paragraph fails `TestThePromptNamesTheKey`.
"""

from __future__ import annotations

import json
import logging

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
    VerdictStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    MockWorkspace,
    _lines_to_stream,
    _make_processor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_prompt import (
    render_workspace_prompt,
)

pytestmark = pytest.mark.unit

#: The production report, from the issue, with its keys and their order intact.
#: Kept whole rather than reduced to ``{"status": "completed"}`` because the
#: extra keys are half of what has to be true: the alias reads a block that
#: carries ``branch``, ``commit`` and ``pr`` beside the outcome, which is what
#: an agent inventing a schema actually writes.
THE_SHAPE_THAT_LOST_A_PHASE = (
    "TASK_RESULT:\n"
    '{"status": "completed", "branch": "perf/1253-heatmap-bounded-reads", '
    '"commit": "7e96e27c0b1e4d2a8f3c5b6a9d0e1f2a3b4c5d6e", "pr": 1371, '
    '"artifact": "artifacts/output/implement.md", "files_changed": 6}\n'
    "TASK_RESULT_END"
)

#: The same invention in the refusing direction. An alias that read only
#: ``completed`` would turn every blocked phase into a pass, which is the one
#: direction `phase_verdict` exists to close - so both spellings are read or
#: neither may be.
A_STATUS_FAILED_REPORT = (
    'TASK_RESULT: {"status": "failed", '
    '"comments": "GitHub App not installed on repo org/repo"}\nTASK_RESULT_END'
)


class TestTheTwoExactSpellingsAreRead:
    """A finished phase is not failed over the name of the key it used."""

    def test_status_completed_is_the_success_the_phase_reported(self) -> None:
        verdict = AgentVerdict.from_agent_text(THE_SHAPE_THAT_LOST_A_PHASE)

        assert verdict.status is VerdictStatus.SUCCESS
        assert not verdict.refuses_completion
        assert verdict.via_status_alias

    def test_a_block_with_no_comments_still_tells_an_operator_what_happened(self) -> None:
        """The invented schema has no ``comments``, so there is nothing to quote.

        An empty string here would reach an operator as "the agent said
        nothing", which is a different and wrong fact: the agent said plenty,
        under keys the contract does not describe.
        """
        verdict = AgentVerdict.from_agent_text(THE_SHAPE_THAT_LOST_A_PHASE)

        assert "status" in verdict.comments
        assert "completed" in verdict.comments
        assert "#1324" in verdict.comments

    def test_status_failed_refuses_the_phase_and_quotes_the_agent(self) -> None:
        verdict = AgentVerdict.from_agent_text(A_STATUS_FAILED_REPORT)

        assert verdict.status is VerdictStatus.FAILURE
        assert verdict.refuses_completion
        assert verdict.comments == "GitHub App not installed on repo org/repo"


class TestEverythingElseIsUnreadableExactlyAsBefore:
    """The closed half. These rows are why the alias is an alias and not a mode."""

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(
                'TASK_RESULT: {"status": "Completed"}\nTASK_RESULT_END',
                id="status-completed-capitalised",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "COMPLETED"}\nTASK_RESULT_END',
                id="status-completed-shouted",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "completed "}\nTASK_RESULT_END',
                id="status-completed-with-a-trailing-space",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "done"}\nTASK_RESULT_END',
                id="status-done-is-not-one-of-the-two",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "success"}\nTASK_RESULT_END',
                id="status-success-is-not-one-of-the-two",
            ),
            pytest.param(
                'TASK_RESULT: {"status": true}\nTASK_RESULT_END',
                id="status-is-a-boolean-not-a-string",
            ),
            pytest.param(
                'TASK_RESULT: {"status": 1}\nTASK_RESULT_END',
                id="status-is-a-number",
            ),
            pytest.param(
                'TASK_RESULT: {"status": null}\nTASK_RESULT_END',
                id="status-is-null",
            ),
            pytest.param(
                'TASK_RESULT: {"status": ["completed"]}\nTASK_RESULT_END',
                id="status-is-a-list-containing-the-word",
            ),
            pytest.param(
                'TASK_RESULT: {"success": "true", "comments": "done"}\nTASK_RESULT_END',
                id="success-is-still-a-string-and-still-refused",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "completed", "success": "true"}\nTASK_RESULT_END',
                id="an-unreadable-success-is-not-rescued-by-a-status",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "completed", "success": null}\nTASK_RESULT_END',
                id="a-null-success-was-still-written-so-it-is-not-the-alias-shape",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "completed", "pr": 1371}',
                id="the-alias-shape-without-its-terminator",
            ),
        ],
    )
    def test_a_near_miss_is_unreadable_and_refuses_the_phase(self, text: str) -> None:
        """One row per spelling, and each is a refusal rather than a pass.

        The last row is the one that says the alias changed nothing about the
        grammar: a block is still three parts, and ``status`` does not buy an
        agent the terminator it did not write.
        """
        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.UNREADABLE
        assert verdict.refuses_completion
        assert not verdict.via_status_alias


#: Every shape a ``status`` member takes beside a ``success`` the contract can
#: read: absent, both alias spellings, a word outside the vocabulary, the wrong
#: case, and values that are not strings at all. The rule is that NONE of them
#: means anything, so the matrix below is this list crossed with both booleans
#: rather than a row per interesting case - the uninteresting ones are the
#: point, and a list that stopped at the two disagreements would be asserting
#: the old policy with its sign flipped.
A_STATUS_MEMBER_OF_EVERY_SHAPE = [
    pytest.param("", id="status-absent"),
    pytest.param(', "status": "completed"', id="status-completed"),
    pytest.param(', "status": "failed"', id="status-failed"),
    pytest.param(', "status": "in_progress"', id="status-outside-the-vocabulary"),
    pytest.param(', "status": "Failed"', id="status-wrong-case"),
    pytest.param(', "status": "COMPLETED"', id="status-shouted"),
    pytest.param(', "status": true', id="status-is-a-boolean"),
    pytest.param(', "status": 1', id="status-is-a-number"),
    pytest.param(', "status": null', id="status-is-null"),
    pytest.param(', "status": ["failed"]', id="status-is-a-list"),
    pytest.param(', "status": {"value": "failed"}', id="status-is-an-object"),
]

#: Both booleans, and what each obliges. Written once and shared by the tests
#: below so that neither can be quietly narrowed to the completing direction.
BOTH_DIRECTIONS_OF_THE_CONTRACT = [
    pytest.param("true", VerdictStatus.SUCCESS, id="success-true"),
    pytest.param("false", VerdictStatus.FAILURE, id="success-false"),
]


class TestAStatusKeyBesideAReadableSuccessIsIgnored:
    """The contract answers alone wherever it can, and ``status`` is an extra key.

    The alias gave ``status`` a meaning, and the obvious next step was to weigh
    the two keys when a block wrote both - refusing
    ``{"success": true, "status": "failed"}`` because it says two opposite
    things. That is the policy this class exists to rule out, and the reason is
    not that the disagreement is harmless:

      - it lets a key the prompt tells agents NEVER to write refuse a phase
        that wrote the contract's key correctly and with the contract's type,
        which is "SUCCESS became UNREADABLE" - defect (2) in `phase_verdict`'s
        docstring - in a new spelling;
      - and it makes the alias able to change a reading, which is exactly what
        was promised it could never do.

    So ``success`` is read and returned, and every ``status`` beside it is an
    extra key that the contract ignores as it ignores ``branch`` and ``pr`` -
    the behaviour on `main`, unchanged by this issue in either direction.
    """

    @pytest.mark.parametrize("status_member", A_STATUS_MEMBER_OF_EVERY_SHAPE)
    @pytest.mark.parametrize(("success_written", "expected"), BOTH_DIRECTIONS_OF_THE_CONTRACT)
    def test_the_verdict_is_whatever_success_states(
        self, success_written: str, status_member: str, expected: VerdictStatus
    ) -> None:
        """Twenty-two rows, one rule: the ``status`` member is not consulted.

        ``comments`` is asserted because it is the evidence of WHICH model
        read the block. `_StatusAliasResult` writes its own sentence there
        when it reads a block, so a row that came back with the agent's own
        words came back from the contract - the status member did not merely
        fail to change the outcome, it was never read.
        """
        text = (
            f'TASK_RESULT: {{"success": {success_written}{status_member}, '
            f'"comments": "opened PR #1371"}}\nTASK_RESULT_END'
        )

        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is expected
        assert verdict.refuses_completion is (expected is VerdictStatus.FAILURE)
        assert not verdict.via_status_alias
        assert verdict.comments == "opened PR #1371"

    @pytest.mark.parametrize("status_member", A_STATUS_MEMBER_OF_EVERY_SHAPE)
    def test_ignored_means_ignored_including_in_the_log(
        self, status_member: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A report that obeyed the contract is not warned about for an extra key.

        This pins a decision rather than a mechanism, which is why it is worth
        a test of its own: "ignored" was briefly implemented as "read, found
        harmless, and logged". A warning on every block carrying a second key
        is a line an operator has to triage for a report that did nothing
        wrong, and it is the last trace of the policy above - the one place
        the two keys would still be compared. `main` logs nothing here and
        neither does this.
        """
        with caplog.at_level(
            logging.WARNING,
            logger="syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict",
        ):
            verdict = AgentVerdict.from_agent_text(
                f'TASK_RESULT: {{"success": true{status_member}}}\nTASK_RESULT_END'
            )

        assert verdict.status is VerdictStatus.SUCCESS
        assert caplog.records == []

    def test_the_refusal_for_a_written_false_is_the_contract_one_whatever_status_says(
        self,
    ) -> None:
        """The operator is told what the agent reported, not what it also wrote.

        `WorkflowExecutionProcessor` raises this string. The phase failed on
        ``success: false``; mentioning the ``status`` beside it - or crediting
        the refusal to the #1324 alias - would describe a reading that did not
        happen.
        """
        refusal = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"success": false, "status": "completed", '
            '"comments": "could not push"}\nTASK_RESULT_END'
        ).refusal(phase_id="implement")

        assert "TASK_RESULT success=false" in refusal
        assert "could not push" in refusal
        assert "#1324" not in refusal


class TestABlockThatWritesStatusTwice:
    """The one way a block can still name its outcome twice: under the same key.

    ``{"status": "failed", "status": "completed"}`` is legal JSON, and a JSON
    decoder keeps the LAST of duplicate members. So the alias would read that
    block as a plain, exact success while the failure the agent wrote was
    deleted by the parser - a false completion that the block itself
    contradicts in writing, and one that `main` does not have, because there
    ``status`` is not read at all and the same document is unreadable.

    The tell is that swapping the two members swaps the verdict: the outcome
    would be decided by the order of two identical keys, which is the TEXT
    deciding what a report means - defect (1) in `phase_verdict`'s docstring,
    arriving through the alias. There is no reading of the block that is safe
    to act on, so it is UNREADABLE and the phase reruns.
    """

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                '{"status": "failed", "status": "completed"}',
                id="the-false-success-a-failure-overwritten-by-a-success",
            ),
            pytest.param(
                '{"status": "completed", "status": "failed"}',
                id="the-same-two-members-the-other-way-round",
            ),
            pytest.param(
                '{"status": "completed", "status": "completed"}',
                id="the-same-value-twice-so-nothing-was-overwritten",
            ),
            pytest.param(
                '{"status": "failed", "status": "failed"}',
                id="the-same-refusal-twice",
            ),
            pytest.param(
                '{"sta\\u0074us": "failed", "status": "completed"}',
                id="an-escaped-key-is-the-same-key",
            ),
            pytest.param(
                '{"status": "completed", "sta\\u0074us": "failed"}',
                id="an-escaped-key-is-the-same-key-in-either-position",
            ),
            pytest.param(
                '{"status": "completed", "comments": "opened PR #1371", "status": "failed"}',
                id="the-duplicates-need-not-be-adjacent",
            ),
        ],
    )
    def test_a_repeated_status_is_unreadable_rather_than_read_off_the_survivor(
        self, body: str
    ) -> None:
        """The identical-value rows are not padding, and neither is the escape.

        ``{"status": "completed", "status": "completed"}`` loses nothing when
        the decoder picks a winner, so a rule written as "the duplicates
        disagree" would let it through - and it would then be the shape to
        write to get a duplicate past the check. The question is whether the
        block named its outcome once, not whether the namings differ.

        ``"sta\\u0074us"`` decodes to exactly ``status``, so a check that
        counted the key in the raw TEXT would see two different keys and read
        the block off the survivor. Counting the members after decoding is
        what makes the escape equivalent here, as JSON says it is.
        """
        verdict = AgentVerdict.from_agent_text(f"TASK_RESULT: {body}\nTASK_RESULT_END")

        assert verdict.status is VerdictStatus.UNREADABLE
        assert verdict.refuses_completion
        assert not verdict.via_status_alias

    def test_an_escaped_key_written_once_is_still_read_as_the_alias(self) -> None:
        """The control the escape rows need, and the reason they prove anything.

        Refusing every escaped key would pass the duplicate rows for the wrong
        reason. ``{"sta\\u0074us": "completed"}`` is one member spelled
        unusually, and it reads as the alias exactly as the plain spelling
        does - so what the duplicate rows detect is the repetition and not the
        escape.
        """
        verdict = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"sta\\u0074us": "completed"}\nTASK_RESULT_END'
        )

        assert verdict.status is VerdictStatus.SUCCESS
        assert verdict.via_status_alias

    @pytest.mark.parametrize(("success_written", "expected"), BOTH_DIRECTIONS_OF_THE_CONTRACT)
    def test_a_repeated_status_changes_nothing_for_a_block_that_wrote_success(
        self, success_written: str, expected: VerdictStatus
    ) -> None:
        """``success``-present behaviour did not move, and this is where it would.

        The repeat guard is a rule of the ALIAS - it stops a reading that only
        the alias performs. Applying it to every block would make
        ``{"success": false, "status": "x", "status": "y"}`` unreadable, which
        refuses a phase that reported correctly over two members the contract
        never looks at. A duplicate under a key that is ignored is still
        ignored.
        """
        text = (
            f'TASK_RESULT: {{"success": {success_written}, "status": "completed", '
            f'"status": "failed", "comments": "opened PR #1371"}}\nTASK_RESULT_END'
        )

        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is expected
        assert verdict.comments == "opened PR #1371"

    def test_a_repeat_deeper_in_the_block_is_not_the_block_naming_its_outcome_twice(
        self,
    ) -> None:
        """Only the outermost object states the phase's outcome.

        A repeated key inside ``detail`` is a malformed note, not an ambiguous
        verdict: the top-level ``status`` here says ``completed`` once and
        unambiguously. Refusing this would fail a phase for the shape of a
        field nothing reads.
        """
        verdict = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"status": "completed", '
            '"detail": {"status": "failed", "status": "completed"}}\nTASK_RESULT_END'
        )

        assert verdict.status is VerdictStatus.SUCCESS
        assert verdict.via_status_alias

    def test_a_repeated_key_that_names_no_outcome_changes_nothing(self) -> None:
        """Agents write duplicate keys in their invented schemas; most mean nothing.

        Only the member the alias READS can make a verdict depend on which
        duplicate survived. Refusing the rest would turn the guard into a JSON
        style check applied to blocks that state their outcome perfectly well.
        """
        verdict = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"status": "completed", "pr": 1371, "pr": 1372}\nTASK_RESULT_END'
        )

        assert verdict.status is VerdictStatus.SUCCESS
        assert verdict.via_status_alias

    def test_the_repeat_is_named_in_the_log_because_the_refusal_cannot_name_it(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The operator's only route to the real reason, so it is asserted.

        `refusal` tells them the block "is not JSON, or it is not closed" -
        true of most unreadable blocks and false of this one, which is
        well-formed and terminated. Giving `AgentVerdict` another field so the
        sentence could say so would put a wording concern in the type every
        caller sees; the log line carries it instead, and this test is what
        keeps it from being dropped as noise.
        """
        with caplog.at_level(
            logging.WARNING,
            logger="syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict",
        ):
            AgentVerdict.from_agent_text(
                'TASK_RESULT: {"status": "failed", "status": "completed"}\nTASK_RESULT_END'
            )

        warnings = [record.getMessage() for record in caplog.records]
        assert len(warnings) == 1, f"expected one warning about the repeat, got {warnings}"
        assert "more than once" in warnings[0]
        assert '"status"' in warnings[0]
        assert "#1324" in warnings[0]


class TestTheDriftIsVisibleRatherThanAbsorbed:
    """An alias nobody can see is how the drift quietly becomes the format."""

    def test_reading_the_alias_warns_with_the_spelling_and_the_payload(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(
            logging.WARNING,
            logger="syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict",
        ):
            AgentVerdict.from_agent_text(THE_SHAPE_THAT_LOST_A_PHASE)

        warnings = [record.getMessage() for record in caplog.records]
        assert len(warnings) == 1, f"expected one warning about the alias, got {warnings}"
        assert '"status": "completed"' in warnings[0]
        assert "#1324" in warnings[0]
        assert "pr" in warnings[0], "the warning does not show what the agent actually wrote"

    def test_a_contract_shaped_report_says_nothing_about_an_alias(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The control. A phase reporting correctly must not be warned about."""
        with caplog.at_level(
            logging.WARNING,
            logger="syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict",
        ):
            verdict = AgentVerdict.from_agent_text(
                'TASK_RESULT: {"success": true, "comments": "opened PR #1371"}\nTASK_RESULT_END'
            )

        assert verdict.status is VerdictStatus.SUCCESS
        assert not verdict.via_status_alias
        assert caplog.records == []

    def test_a_refusal_says_the_phase_reported_status_rather_than_success(self) -> None:
        """The line an operator greps for must quote what the agent wrote.

        `WorkflowExecutionProcessor` logs this string and raises it as the
        phase's failure reason. Saying "ended with TASK_RESULT success=false"
        about a report that contains no ``success`` sends the reader looking
        for a key that is not in the transcript.
        """
        refusal = AgentVerdict.from_agent_text(A_STATUS_FAILED_REPORT).refusal(phase_id="implement")

        assert "implement" in refusal
        assert '"status": "failed"' in refusal
        assert "#1324" in refusal
        assert "GitHub App not installed on repo org/repo" in refusal

    def test_a_contract_failure_keeps_the_refusal_it_always_had(self) -> None:
        """The other control: the common path's wording did not move."""
        refusal = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"success": false, "comments": "could not push"}\nTASK_RESULT_END'
        ).refusal(phase_id="implement")

        assert "TASK_RESULT success=false" in refusal
        assert "#1324" not in refusal


class TestTheVerdictReachesThePhaseResult:
    """The hop that matters: what the stream hands the processor to act on.

    `AgentVerdict` being right proves nothing on its own - the value has to
    survive `EventStreamProcessor` and arrive on `StreamResult.verdict`, which
    is the only thing `WorkflowExecutionProcessor` ever reads. That is the hop
    #1256's second defect died on.
    """

    async def test_a_finished_phase_reporting_status_completed_is_not_refused(self) -> None:
        result_line = json.dumps(
            {"type": "result", "result": THE_SHAPE_THAT_LOST_A_PHASE, "usage": {}}
        )

        result = await _make_processor().process_stream(
            _lines_to_stream(result_line), MockWorkspace()
        )

        assert result.verdict.status is VerdictStatus.SUCCESS
        assert not result.verdict.refuses_completion, (
            "the shape from exec-cd5e75eaeb63 still fails a phase that finished its work"
        )

    async def test_a_phase_reporting_status_failed_is_still_refused(self) -> None:
        result_line = json.dumps({"type": "result", "result": A_STATUS_FAILED_REPORT, "usage": {}})

        result = await _make_processor().process_stream(
            _lines_to_stream(result_line), MockWorkspace()
        )

        assert result.verdict.refuses_completion
        assert result.verdict.status is VerdictStatus.FAILURE

    async def test_a_status_disagreeing_with_a_written_success_does_not_refuse_the_phase(
        self,
    ) -> None:
        """The whole cost of the cross-key policy, measured where it was paid.

        A phase that did its work, wrote the contract's key correctly, and
        added a stray ``status`` would have been refused here - and a refusal
        at this hop ends the run, which is the $10.76 this issue is about
        arriving by the route that was supposed to fix it.
        """
        report = (
            'TASK_RESULT: {"success": true, "status": "failed", '
            '"comments": "opened PR #1371"}\nTASK_RESULT_END'
        )
        result_line = json.dumps({"type": "result", "result": report, "usage": {}})

        result = await _make_processor().process_stream(
            _lines_to_stream(result_line), MockWorkspace()
        )

        assert result.verdict.status is VerdictStatus.SUCCESS
        assert not result.verdict.refuses_completion

    async def test_a_phase_that_wrote_status_twice_is_refused(self) -> None:
        """The false completion, at the only place that could act on it.

        `StreamResult.verdict` is what `WorkflowExecutionProcessor` reads, so
        a block whose failure was overwritten by a duplicate member would
        complete the phase HERE. Asserting it on `AgentVerdict` alone would
        leave the hop untested.
        """
        report = 'TASK_RESULT: {"status": "failed", "status": "completed"}\nTASK_RESULT_END'
        result_line = json.dumps({"type": "result", "result": report, "usage": {}})

        result = await _make_processor().process_stream(
            _lines_to_stream(result_line), MockWorkspace()
        )

        assert result.verdict.status is VerdictStatus.UNREADABLE
        assert result.verdict.refuses_completion


class TestThePromptNamesTheKey:
    """The emitter's half. The parser alias exists because this was only shown.

    ``success`` appeared in the prompt exclusively INSIDE the two copyable
    fences, so an agent that wrote its own block had been told the key by
    example and never by rule. An example is something to copy; it is not
    something an invention gets checked against.
    """

    @pytest.mark.parametrize("clone_repos", [True, False])
    def test_the_prompt_states_the_key_is_success_and_never_status(self, clone_repos: bool) -> None:
        prompt = render_workspace_prompt(clone_repos=clone_repos)

        assert "`success`, never `status`" in prompt, (
            "the prompt does not rule out the key name that lost exec-cd5e75eaeb63"
        )
        assert "JSON boolean `true` or `false`" in prompt

    @pytest.mark.parametrize("clone_repos", [True, False])
    def test_the_rule_is_stated_before_the_fences_it_governs(self, clone_repos: bool) -> None:
        """An agent that skims to the first code fence never reads what follows it.

        Position is the whole content of this test: the same sentence placed
        under the examples is read by exactly the agents who did not need it.
        """
        prompt = render_workspace_prompt(clone_repos=clone_repos)

        rule_at = prompt.index("`success`, never `status`")
        first_fence_at = prompt.index("```\nTASK_RESULT: ")

        assert rule_at < first_fence_at

    @pytest.mark.parametrize("clone_repos", [True, False])
    def test_the_prompt_does_not_offer_status_as_an_alternative(self, clone_repos: bool) -> None:
        """The alias is a repair, not a second spelling of the contract.

        A prompt that mentioned ``status`` as something the platform accepts
        would make the drift the format, and the next invented key would have
        no reason to stop at two. Every mention here must be the prohibition.
        """
        prompt = render_workspace_prompt(clone_repos=clone_repos)

        assert prompt.count("`success`, never `status`") == 1
        assert prompt.count("status") == 1, (
            "the prompt says `status` somewhere other than the sentence forbidding it"
        )
