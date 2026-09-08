"""A phase that correctly does nothing still has to report (#1221).

THE REPRODUCTION. `open_pr` is handed a passing verification report and a
branch that is already pushed. It checks, finds the PR open at the verified
head, and correctly declines to open a second one - that is the behaviour the
phase is FOR. Then it exits without writing `artifacts/output/deliverable.md`,
because it had nothing it recognised as a deliverable, and #1167's contract
check fails the whole execution:

    Phase 'open_pr' (Open the pull request) declares output_artifacts (markdown)
    but produced none: nothing collectable was written under artifacts/output/.

The work was fine and verification had already passed. Only the status was
wrong. 6 of the last 100 executions, $81.42.

WHERE THE DEFECT ACTUALLY WAS, which is one layer up from where it shows.
The workspace prompt is the platform's own statement of what every phase must
produce, and its "Completing Your Task" section made the deliverable step 4 of
a four-step action sequence whose earlier steps were "make changes", "commit",
"push". Every field step 4 asked for presupposed those had happened - "what you
actually changed", "your actual commit hashes", "the actual PR URL you
created". A phase whose honest answer was "nothing needed doing" could answer
none of them and was given no instruction for its own case. Writing the
deliverable was conditional on having acted.

WHAT THESE TESTS PIN:

  (a) the requirement is stated BEFORE the coding/non-coding split, so it is
      not reachable only by walking an action sequence
  (b) the no-action outcome is named as a reportable one, with the evidence
      as its content
  (c) a cloning phase gets the same guarantee as a no-checkout one - the
      defect is in the shared template and `implement` hits it too
  (d) the fields step 4 asks for are answerable by a phase that acted and by
      one that found the work already done

(c) is the anti-carve-out guard and the one worth keeping. `open_pr` is the
phase that reproduced this, and it is `clone_repos: false`, so a fix confined
to the no-checkout rendering would close the reproduction and leave the
identical bug in the branch that every other phase reads.

WHAT THIS DOES NOT WEAKEN. #1167 still fails a phase that writes nothing, and
must - it is what catches a phase that silently did nothing. See
`test_empty_artifact_recovers_the_verdict`'s
`test_wrote_nothing_and_wrote_empty_are_different_errors`, which is unchanged
and still passes. This removes the reason a CORRECT phase had to trip that
check; it does not teach the check to look away.

WHAT THESE TESTS CANNOT PROVE. That an agent obeys the instruction. They pin
the contract the agent is given, at the point it is actually given it, which
is the whole of what a prompt-level fix can be held to. The measurement that
would close the loop is the failure rate of `open_pr` on subsequent runs.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.test_open_pr_needs_no_working_tree import (
    _executable_phases,
    _provision,
)

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit

#: A verification report with no defect - the state that produces the no-op.
#: The blocking report exercises the REFUSAL path, which already writes
#: reliably; using it here would test the outcome that was never broken.
_PASSING_VERIFY_REPORT = """# Verification report

**Verdict: PASS.** `just preflight-agent` is green and the two mutations were
killed. The branch is pushed at 9f2c1ab and the PR already tracks it.
"""

#: The heading the requirement must sit under, and the one it must sit ABOVE.
#: Splitting on both is what makes (a) a structural claim rather than a search:
#: text found anywhere in a 3kB prompt would also be satisfied by a fix that
#: buried the rule inside the coding branch, where a non-coding phase - and a
#: phase reading the list as a sequence - would never reach it.
_SECTION = "## Completing Your Task"
_SPLIT = "### For coding tasks"


def _stated_for_every_task_kind(prompt: str) -> str:
    """What "Completing Your Task" says before it splits by kind of task.

    This region is the only part of the prompt that both kinds of phase read,
    so it is the only place an unconditional requirement can actually be
    unconditional. On the unfixed template it is empty.
    """
    _, heading, rest = prompt.partition(f"{_SECTION}\n\n")
    assert heading, f"the prompt no longer has a `{_SECTION}` section"
    shared, split, _ = rest.partition(_SPLIT)
    assert split, f"`{_SECTION}` no longer splits on `{_SPLIT}`"
    return shared


async def _prompt_for(phase_id: str) -> str:
    """The prompt as the agent for `phase_id` actually receives it.

    Provisioned rather than rendered: `render_workspace_prompt` is two hops
    from the agent, and `_wiring._build_workspace_prompt` has to read
    `phase.clone_repos` and pick a rendering in between. A template that is
    correct and a caller that selects the wrong branch both look right from
    either end.
    """
    phases = await _executable_phases()
    provisioned = await _provision(
        phases[phase_id],
        completed={"verify": _PASSING_VERIFY_REPORT} if phase_id == "open_pr" else {},
    )
    return provisioned.prompt


class TestTheRequirementIsNotReachableOnlyByHavingActed:
    """(a) and (b), on the phase that reproduced the failure."""

    async def test_the_no_checkout_phase_is_told_to_report_whatever_it_concludes(self) -> None:
        """`open_pr` is `clone_repos: false`; this is the reproduction's shape."""
        shared = _stated_for_every_task_kind(await _prompt_for("open_pr"))

        assert shared.strip(), (
            "`Completing Your Task` says nothing before it splits by task kind, "
            "so the deliverable requirement is reachable only by reading one of "
            "the two branches - which is the #1221 defect itself"
        )
        assert "artifacts/output/" in shared, (
            f"the shared region must name where the report goes, got {shared!r}"
        )

    async def test_no_action_required_is_named_as_a_reportable_outcome(self) -> None:
        """(b). The phase already knows it is in this case; the contract has to
        give it somewhere to say so, and say what the content is.

        The content matters as much as the requirement: a phase told only "always
        write a file" writes a file saying "nothing to do", which is a deliverable
        in name and evidence of nothing.
        """
        shared = _stated_for_every_task_kind(await _prompt_for("open_pr"))

        assert "not conditional on having acted" in shared, (
            f"the rule has to be stated as a rule, got {shared!r}"
        )
        assert "already done" in shared, (
            f"the no-op outcome must be named, not left implied, got {shared!r}"
        )
        assert "what you checked" in shared, (
            "the deliverable for a no-op is the EVIDENCE that established it; "
            f"without that this instructs an empty confirmation, got {shared!r}"
        )

    async def test_declining_and_being_unable_stay_distinct_outcomes(self) -> None:
        """The refusal path already worked and must not be collapsed into the
        no-op path by a fix aimed at the no-op path.

        "I declined because acting would be wrong" and "I could not act" are
        different incidents with different follow-ups, and #1221's own proposal
        lists them separately for that reason.
        """
        shared = _stated_for_every_task_kind(await _prompt_for("open_pr"))

        assert "declined to act" in shared
        assert "could not act" in shared


class TestTheGuaranteeIsNotConfinedToTheReproduction:
    """(c) The anti-carve-out guard."""

    async def test_a_cloning_phase_gets_the_identical_requirement(self) -> None:
        """`implement` clones, and #1221 records it failing the same way.

        Equality against `open_pr`'s region rather than a second substring
        search: the two renderings differ by design (#1187), and the claim here
        is precisely that they do NOT differ in this section.

        Equality ALONE would be vacuous, and was - on the unfixed template both
        regions are empty, so this passed while proving nothing. The content
        assertion is what makes it able to fail; the equality is what makes a
        fix confined to the no-checkout rendering fail it.
        """
        cloning = _stated_for_every_task_kind(await _prompt_for("implement"))

        assert "not conditional on having acted" in cloning, (
            "a cloning phase must get the rule too - `implement` is the other "
            f"phase #1221 measured failing this way, got {cloning!r}"
        )
        assert cloning == _stated_for_every_task_kind(await _prompt_for("open_pr"))


class TestTheFieldsAreAnswerableWithoutHavingActed:
    """(d) The step-4 bullets, which are where the presupposition actually bit.

    Restating the rule above the split while leaving the fields demanding a
    commit hash and a PR the phase created would leave the agent with a
    requirement it still cannot satisfy - and an agent that cannot satisfy the
    fields is the agent that wrote nothing.
    """

    async def test_the_pr_field_admits_a_pr_that_was_already_open(self) -> None:
        """The exact reproduction: the PR exists and this phase did not open it."""
        prompt = await _prompt_for("open_pr")

        assert "the one you opened, or the one that was already there" in prompt, (
            "the PR URL field still presupposes this phase created the PR, which "
            "is false in every run that reproduced #1221"
        )

    async def test_the_change_and_commit_fields_admit_having_changed_nothing(self) -> None:
        prompt = await _prompt_for("open_pr")

        assert "or what you found already correct" in prompt
        assert "if you made any" in prompt, (
            "a phase that committed nothing must not be asked for commit hashes as though it had"
        )
