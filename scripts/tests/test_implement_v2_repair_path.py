"""`sdlc-implement-v2`'s repair path must stay safe to run.

The fix/reverify pair exists to rescue a run that verification found a defect
in. Everything that makes that rescue trustworthy is prose in a prompt file:
which artifact a phase reads, which commit it checks out, which gate it runs,
and which SHA it hands to the phase after it. There is no code path to assert
against - the safeguard IS the instruction the agent reads.

That makes the realistic regression silent. Deleting the checkout block from
`fix.md` leaves a workflow that loads, converts, installs and runs; it just
repairs whatever tree the clone happened to land on. `check_workflow_definitions`
cannot see it, because the definition is still valid. What comes out the far end
is a PR certified against a commit nobody reviewed.

Each test below is one of the five blocking findings the cross-model review
raised on #1361, phrased as the property that finding's fix established. They
run against the COMMAND the create endpoint builds, not the files on disk:
`prompt_file` is resolved during load and the text becomes `prompt_template`,
so reading the markdown back would confirm what was typed while telling us
nothing about what the platform installs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / "workflows" / "sdlc" / "implement" / "workflow.yaml"


@pytest.fixture(scope="module")
def prompts() -> dict[str, str]:
    """Every phase's prompt as `POST /workflows` installs it, on one line each.

    Whitespace is collapsed because these files are hard-wrapped at 80 columns
    and the sentences asserted on straddle the wrap. Matching the raw text would
    make re-flowing a paragraph fail the suite - which is noise, and worse, it
    teaches the next person that the cheap way to a green suite is to delete the
    assertion. Collapsing leaves the shell lines intact: none of them contain a
    run of whitespace.
    """
    command = build_command_from_definition(WorkflowDefinition.from_file(_WORKFLOW))
    assert command.aggregate_id == "sdlc-implement-v2"
    installed: dict[str, str] = {}
    for phase in command.phases:
        assert phase.prompt_template, f"phase {phase.name!r} installed with no prompt text"
        installed[_phase_key(phase)] = re.sub(r"\s+", " ", phase.prompt_template)
    for required in ("fix", "reverify", "verify", "open_pr"):
        assert required in installed, (
            f"no phase whose prompt is {required}.md reached the installed command; "
            "the repair path is not the shape these tests describe"
        )
    return installed


def _phase_key(phase: PhaseDefinition) -> str:
    """Phases carry their name, not their id, into the built command."""
    return {
        "Check the task's premise": "premise",
        "Make the change": "implement",
        "Verify the change independently": "verify",
        "Address what verification found": "fix",
        "Confirm the fix closed what verification found": "reverify",
        "Open the pull request": "open_pr",
    }.get(phase.name, phase.name)


class TestTheHandoffsSurviveTheDeprecatedAlias:
    """Finding 1: both new phases read only `artifacts/input/<phase>.md`.

    `ArtifactCollector` keeps that flat alias "for one release (issue #988)".
    A phase that reads only it receives an empty string the day it goes, and an
    empty report reads exactly like "verification found nothing".
    """

    def test_fix_reads_the_durable_verify_artifact(self, prompts: dict[str, str]) -> None:
        assert "artifacts/input/verify/verify.md" in prompts["fix"]

    def test_fix_still_falls_back_to_the_alias(self, prompts: dict[str, str]) -> None:
        """The alias exists today; dropping it breaks the path before #988 lands."""
        assert "artifacts/input/verify.md" in prompts["fix"]

    def test_reverify_reads_both_durable_artifacts(self, prompts: dict[str, str]) -> None:
        assert "artifacts/input/fix/fix.md" in prompts["reverify"]
        assert "artifacts/input/verify/verify.md" in prompts["reverify"]

    def test_fix_stops_rather_than_guessing_when_input_is_missing(
        self, prompts: dict[str, str]
    ) -> None:
        """Silence must not be read as "nothing to do" - it is "no input"."""
        prompt = prompts["fix"].lower()
        assert "if neither exists" in prompt
        assert "stop without changing or pushing anything" in prompt


class TestFixOperatesOnTheReviewedCommit:
    """Finding 2: `fix` began in a fresh clone of the default branch.

    Without a checkout it edits `main`, builds a repair against the wrong tree,
    and cannot push where the branch actually is.
    """

    def test_it_checks_out_the_verified_sha(self, prompts: dict[str, str]) -> None:
        prompt = prompts["fix"]
        assert "git fetch origin <branch>" in prompt
        assert "git checkout -B <branch> <verified-sha>" in prompt

    def test_it_confirms_the_remote_has_not_moved(self, prompts: dict[str, str]) -> None:
        """Checking out the right SHA proves nothing if origin has since moved on."""
        assert "git rev-parse origin/<branch>" in prompts["fix"]

    def test_it_refuses_on_mismatch_instead_of_repairing_anyway(
        self, prompts: dict[str, str]
    ) -> None:
        prompt = prompts["fix"].lower()
        assert "do not edit and do not push" in prompt

    def test_it_forbids_force_pushing(self, prompts: dict[str, str]) -> None:
        """A non-fast-forward push here would destroy the head verify reviewed."""
        assert "never force-push" in prompts["fix"].lower()


class TestFixRunsAGateThisWorkspaceHas:
    """Finding 3: it mandated `just preflight`, which agent workspaces cannot run.

    The image ships `just`, `uv` and `node`; `vsa`, Cargo, pnpm and Docker are
    absent (#1109). A mandated gate that always fails teaches the agent to skip
    gates.
    """

    def test_it_names_the_agent_gate(self, prompts: dict[str, str]) -> None:
        assert "just preflight-agent" in prompts["fix"]
        assert "uv run pytest -m unit -q" in prompts["fix"]

    def test_it_never_asks_for_the_full_preflight(self, prompts: dict[str, str]) -> None:
        """Matched with a negative lookahead: `just preflight-agent` contains
        `just preflight`, so a plain substring check passes over the defect."""
        stray = re.search(r"just preflight(?!-agent)", prompts["fix"])
        assert stray is None, (
            f"fix.md asks for the full preflight at offset {stray.start() if stray else -1}; "
            "that target cannot run in an agent workspace"
        )

    def test_it_sets_tmpdir_so_the_gate_reaches_the_change(self, prompts: dict[str, str]) -> None:
        """`/tmp` is `noexec`; without this `just` dies on its first shebang recipe."""
        assert "TMPDIR=/workspace/.tmp" in prompts["fix"]


class TestReverifyChecklistComesFromVerifyNotFix:
    """Finding 4: `reverify` read only `fix.md` - written by the agent it checks.

    A `fix.md` that omits, merges or misstates a blocker would otherwise define
    reverify's entire scope, and a partial repair certifies.
    """

    def test_verify_is_named_as_the_authoritative_enumeration(
        self, prompts: dict[str, str]
    ) -> None:
        prompt = prompts["reverify"].lower()
        assert "authoritative enumeration of blocking defects" in prompt

    def test_fix_is_explicitly_barred_from_narrowing_the_checklist(
        self, prompts: dict[str, str]
    ) -> None:
        prompt = prompts["reverify"].lower()
        assert "must not define or narrow the checklist" in prompt

    def test_the_output_enumerates_every_verify_blocker(self, prompts: dict[str, str]) -> None:
        """The report shape is what makes the checklist auditable after the run."""
        prompt = prompts["reverify"].lower()
        assert "not only the ones" in prompt


class TestTheRepairedHeadIdentityContract:
    """Finding 5: nothing tied the SHA `fix` pushed to the SHA `open_pr` opens.

    `reverify` never fetched, never checked out, and was not asked to report a
    head; `open_pr` was told to compare against "the one verification reported",
    which on the repair path is the PRE-FIX commit.
    """

    def test_reverify_derives_a_candidate_sha_from_both_outcomes(
        self, prompts: dict[str, str]
    ) -> None:
        prompt = prompts["reverify"].lower()
        assert "candidate" in prompt
        assert "if `fix.md` says no change was made" in prompt

    def test_reverify_checks_the_candidate_out_and_compares_the_remote(
        self, prompts: dict[str, str]
    ) -> None:
        prompt = prompts["reverify"]
        assert "git checkout <candidate-sha>" in prompt
        assert "git rev-parse origin/<branch>" in prompt
        assert "git rev-parse HEAD" in prompt

    def test_reverify_blocks_rather_than_certifying_a_sha_it_did_not_see(
        self, prompts: dict[str, str]
    ) -> None:
        prompt = prompts["reverify"].lower()
        assert "output blocked" in prompt
        assert "never certify from `fix.md` alone" in prompt

    def test_reverify_inspects_the_repair_diff(self, prompts: dict[str, str]) -> None:
        assert "git diff <first-pass-verified-sha>...<candidate-sha>" in prompts["reverify"]

    def test_reverify_reports_the_certified_branch_and_sha(self, prompts: dict[str, str]) -> None:
        """open_pr's comparison has nothing to compare against otherwise."""
        prompt = prompts["reverify"].lower()
        assert "the branch and the full commit sha you certified" in prompt

    def test_open_pr_compares_against_reverifys_sha_not_the_first_passs(
        self, prompts: dict[str, str]
    ) -> None:
        prompt = prompts["open_pr"].lower()
        assert "`reverify.md` reports as certified" in prompt
        assert "not the one the first pass verified" in prompt

    def test_verify_names_the_branch_fix_must_fetch(self, prompts: dict[str, str]) -> None:
        """The contract starts here: `fix` has only this report to learn the branch."""
        prompt = prompts["verify"].lower()
        assert "name the branch and the full commit sha you verified" in prompt


class TestTheCleanPathStaysCheap:
    """The repair path's guards must not turn the common case into a second full review.

    Verification certifies most runs. If `fix` starts editing or `reverify`
    starts re-reviewing, the SHA contract has been bought with the budget the
    split was created to save.
    """

    def test_fix_changes_nothing_when_verification_certified(self, prompts: dict[str, str]) -> None:
        prompt = prompts["fix"].lower()
        assert "**change nothing**" in prompt

    def test_reverify_does_not_repeat_the_whole_review(self, prompts: dict[str, str]) -> None:
        prompt = prompts["reverify"].lower()
        assert "do not re-run the whole review" in prompt


class TestVerifyHandsOffInsteadOfEndingTheRun:
    """A verify phase that reports a defect as its own failure kills the run.

    The platform fails any phase whose agent ends on `TASK_RESULT success=false`
    (`phase_verdict.py`), and the prompt injected into every phase tells the
    agent that being "blocked" or hitting "an error" means `success=false`. So
    unless verify is told otherwise, a real finding - or a database the
    workspace cannot start - reads as blocked, the verify phase fails, and fix
    never runs. That is the #1358 failure again, one phase earlier. It happened
    in production on 2026-09-19 (exec-3173a246c698): verify found a genuine
    blocker, ended success=false, and $17.44 of work stopped before repair.
    """

    def test_a_blocked_candidate_is_still_a_delivered_report(self, prompts: dict[str, str]) -> None:
        assert (
            "end with `TASK_RESULT success=true` even when the candidate is BLOCKED"
            in prompts["verify"]
        )

    def test_failure_is_reserved_for_verification_that_could_not_run(
        self, prompts: dict[str, str]
    ) -> None:
        assert (
            "Use `TASK_RESULT success=false` only when verification itself could not run at all"
            in prompts["verify"]
        )

    def test_a_partial_environment_limitation_is_a_finding_not_a_failure(
        self, prompts: dict[str, str]
    ) -> None:
        verify = prompts["verify"]
        assert "an environment limitation that prevents only part of verification" in verify
        assert "such as an unavailable database" in verify

    def test_only_open_pr_opens_a_pull_request(self, prompts: dict[str, str]) -> None:
        assert "Only the `open_pr` phase may do that." in prompts["verify"]
