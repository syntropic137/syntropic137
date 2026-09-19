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
  - returning `_CrossKeyReading.ABSENT` unconditionally - the reading before
    the cross-key rule existed - fails every disagreement row and the refusal
    wording; returning `CONTRADICTS` for any block carrying both keys fails
    every agreement row and both near-miss vocabulary rows;
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
    TASK_RESULT_TERMINATOR,
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


class TestABlockThatNamesItsOutcomeTwice:
    """The shape the alias created, and the only one whose reading it changed.

    Before the alias, ``status`` was an extra key and ``extra="ignore"`` was
    right about it: it said nothing, so the contract settled the block alone.
    The alias gives it a meaning, so ``{"success": true, "status": "failed"}``
    is now a block that says two opposite things - and NEITHER model can see
    that. The contract still ignores ``status``; the alias is only reached once
    the contract has refused. Whichever ran first would decide, which is a
    verdict settled by the order of two ``try`` blocks.

    `_read_cross_keys` decides it by rule instead, ahead of both, and the two
    halves below are why it has three states and not a boolean.
    """

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(
                'TASK_RESULT: {"status": "completed", "success": false, '
                '"comments": "could not push"}\nTASK_RESULT_END',
                id="completed-beside-a-written-false",
            ),
            pytest.param(
                'TASK_RESULT: {"status": "failed", "success": true, '
                '"comments": "opened PR #1371"}\nTASK_RESULT_END',
                id="failed-beside-a-written-true",
            ),
            pytest.param(
                'TASK_RESULT: {"success": true, "status": "failed"}\nTASK_RESULT_END',
                id="the-same-disagreement-with-the-keys-the-other-way-round",
            ),
            pytest.param(
                'TASK_RESULT: {"success": false, "status": "completed"}\nTASK_RESULT_END',
                id="the-other-disagreement-with-the-keys-the-other-way-round",
            ),
        ],
    )
    def test_a_disagreement_is_unreadable_whichever_key_was_written_first(self, text: str) -> None:
        """Presence decides this, never order, because order is a property of
        the text - which is what every defect in the module docstring came from
        trusting. All four rows are the same two claims, shuffled.

        ``failed`` beside ``true`` is the row that has to refuse: read by the
        contract alone it COMPLETES a phase whose own block contains a plain
        statement of failure, which is the one direction `phase_verdict` exists
        to close. ``completed`` beside ``false`` refused before and refuses
        still - what changes is that it now refuses for the reason that is
        true of it.
        """
        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.UNREADABLE
        assert verdict.refuses_completion
        assert verdict.self_contradictory
        assert not verdict.via_status_alias

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param(
                'TASK_RESULT: {"success": true, "status": "completed", '
                '"comments": "opened PR #1371"}\nTASK_RESULT_END',
                VerdictStatus.SUCCESS,
                id="a-redundant-completed-beside-a-written-true",
            ),
            pytest.param(
                'TASK_RESULT: {"success": false, "status": "failed", '
                '"comments": "could not push"}\nTASK_RESULT_END',
                VerdictStatus.FAILURE,
                id="a-redundant-failed-beside-a-written-false",
            ),
        ],
    )
    def test_an_agreement_is_read_off_success_exactly_as_it_always_was(
        self, text: str, expected: VerdictStatus
    ) -> None:
        """The other half, and the reason the rule is not "both keys refuse".

        This agent wrote the contract's key, with the contract's type, and one
        redundant key beside it that contradicts nothing. Refusing it would
        fail a report that OBEYED over an extra key - defect (2) in the module
        docstring, SUCCESS became UNREADABLE, in a new spelling - and cost a
        rerun of a finished phase to punish compliance. ``extra="ignore"``
        exists for exactly this and still holds where nothing disagrees.
        """
        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is expected
        assert verdict.refuses_completion is (expected is VerdictStatus.FAILURE)
        assert not verdict.via_status_alias
        assert not verdict.self_contradictory

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(
                'TASK_RESULT: {"success": true, "status": "in_progress"}\nTASK_RESULT_END',
                id="a-status-outside-the-closed-vocabulary-is-not-a-second-claim",
            ),
            pytest.param(
                'TASK_RESULT: {"success": true, "status": "Failed"}\nTASK_RESULT_END',
                id="the-vocabulary-is-exact-here-too-so-a-miscased-status-says-nothing",
            ),
        ],
    )
    def test_a_status_that_names_no_outcome_leaves_the_contract_alone(self, text: str) -> None:
        """The vocabulary is `_StatusAlias` and nothing else, on BOTH sides.

        A near-miss is not a claim the rule may weigh - guessing that
        ``"Failed"`` meant ``failed`` is the guessing the whole module refuses,
        and here it would turn a contract-shaped success into a refusal. So the
        closed set decides what counts as a second outcome exactly as it
        decides what the alias reads, and these blocks are one claim and a note.
        """
        verdict = AgentVerdict.from_agent_text(text)

        assert verdict.status is VerdictStatus.SUCCESS
        assert not verdict.self_contradictory

    def test_the_refusal_says_the_block_disagreed_and_not_that_it_was_malformed(
        self,
    ) -> None:
        """An operator sent to look for broken JSON will not find any.

        `WorkflowExecutionProcessor` raises this string as the phase's failure
        reason. The block here is well-formed JSON, correctly terminated, and
        completely readable; the only thing wrong with it is that it says both
        things. Telling the reader it "is not JSON, or is not closed" is a
        false lead in the one message they get.
        """
        refusal = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"success": true, "status": "failed"}\nTASK_RESULT_END'
        ).refusal(phase_id="implement")

        assert "implement" in refusal
        assert "they disagree" in refusal
        assert "#1324" in refusal
        assert TASK_RESULT_TERMINATOR not in refusal, (
            "the refusal blames a missing terminator on a block that has one"
        )

    def test_an_agreement_is_logged_so_the_drift_is_still_seen(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Not refusing is not the same as not noticing.

        The block is read as it always was, so nothing downstream can tell that
        an agent is writing a key the contract does not ask for. The log line
        is the whole of that signal, and without it a second spelling of the
        result schema spreads with no evidence anywhere that it exists.
        """
        with caplog.at_level(
            logging.WARNING,
            logger="syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict",
        ):
            AgentVerdict.from_agent_text(
                'TASK_RESULT: {"success": true, "status": "completed"}\nTASK_RESULT_END'
            )

        warnings = [record.getMessage() for record in caplog.records]
        assert len(warnings) == 1, f"expected one warning about both keys, got {warnings}"
        assert '"success" and "status"' in warnings[0]
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
