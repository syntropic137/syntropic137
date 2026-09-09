"""`sdlc-pr-review-v1` must install as a gate that can tell "did not run" from "passed".

Same shape as `test_quickfix_workflow.py`, and for the same reason: the
safeguard IS the prompt, so the failure that matters is not "the definition is
invalid" - `check_workflow_definitions` covers that for every workflow in the
tree - it is "the definition is still valid and the safeguard is gone". These
assertions therefore run against the `prompt_template` the create endpoint
builds, not the file on disk.

WHAT WENT WRONG (#1127). The verify phase compared BOTH the recorded base and
the recorded head against the refs it found, and told the agent to stop if
either differed. `origin/main` advances constantly here, so in
exec-3afef2976abe the base had moved by the time verify ran, the phase stopped
without running any of its three checks, and the execution reported success:
the gate got flakier the more active the repository was, and its failures were
invisible. Two things had to change and both are pinned below - the moved base
must not stop the review, and a phase that genuinely cannot review must leave a
different trace from one that reviewed and passed.

`TestTheMovedBaseIsAReviewableSituation` is the part that is not prose. It
builds a real repository where the base has moved and the head has not, and
runs the prompt's OWN checkout commands against it. A prompt that told the
agent to do something impossible in that situation would pass every substring
assertion here and fail that one.
"""

from __future__ import annotations

import re
import subprocess
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
_WORKFLOW = _REPO_ROOT / "workflows" / "sdlc" / "pr-review" / "workflow.yaml"


@pytest.fixture(scope="module")
def verify_prompt() -> str:
    """The verify phase's prompt exactly as `POST /workflows` would install it."""
    command = build_command_from_definition(WorkflowDefinition.from_file(_WORKFLOW))
    assert command.aggregate_id == "sdlc-pr-review-v1"
    phases: dict[str, PhaseDefinition] = {p.phase_id: p for p in command.phases}
    assert set(phases) == {"investigate", "verify", "report"}
    verify = phases["verify"]
    assert verify.provider == "codex", (
        "the verify phase is the cross-model half of this gate; on the same "
        "provider as investigate it is a second opinion from the same model"
    )
    return verify.prompt_template or ""


class TestAMovedBaseDoesNotStopTheReview:
    """The abort must be gone, not softened.

    Asserted both ways round. The positive assertion alone would pass with the
    old ref comparison still sitting above it, which is the state that produced
    a review of nothing.
    """

    def test_it_re_anchors_on_the_recorded_head_instead_of_comparing_refs(
        self, verify_prompt: str
    ) -> None:
        assert "git checkout <recorded-head-sha>" in verify_prompt
        assert "git rev-parse origin/main origin/<pr-branch>" not in verify_prompt, (
            "the base/head comparison is back: this is the check that aborted "
            "the review whenever the default branch had moved (#1127)"
        )

    def test_it_says_plainly_that_a_moved_base_is_not_a_reason_to_stop(
        self, verify_prompt: str
    ) -> None:
        assert "A moved base is not a reason to stop." in verify_prompt
        assert "review the recorded head anyway" in verify_prompt

    def test_a_head_it_cannot_check_out_is_still_a_reason_to_stop(self, verify_prompt: str) -> None:
        """Not-stopping must not have been widened into never-stopping.

        Reviewing whatever the branch points at now, when the commit that was
        mapped is gone, certifies a different commit than the one under review.
        """
        assert "A head you cannot check out IS a reason to stop." in verify_prompt


class TestAPhaseThatCannotVerifySaysSoWhereItCounts:
    """Writing "I stopped" in an artifact nobody parses is what failed before.

    The prompt must route every stopping reason - no input, no SHAs, a vanished
    head - through the one channel the platform reads, and must say that the
    write-up alone is not enough.
    """

    def test_it_requires_the_failure_to_be_declared_in_the_result_block(
        self, verify_prompt: str
    ) -> None:
        assert 'TASK_RESULT: {"success": false' in verify_prompt

    def test_it_covers_every_stopping_reason_not_only_the_vanished_head(
        self, verify_prompt: str
    ) -> None:
        assert "every reason this phase can be unable to do its job" in verify_prompt
        assert "no input from the previous phase" in verify_prompt

    def test_the_missing_input_path_routes_through_the_same_stopping_rule(
        self, verify_prompt: str
    ) -> None:
        """The shared boilerplate used to end at "stop and say so", full stop.

        That is the same defect one hop over: an abort a completed phase can
        still report as a success.
        """
        assert "so that stopping is recorded as stopping" in verify_prompt

    def test_it_states_the_invariant_the_phase_exists_to_uphold(self, verify_prompt: str) -> None:
        assert (
            '"I could not verify" must never leave the same trace as\n"I verified and it passed."'
            in verify_prompt
        )


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(cwd),
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
    )


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", name, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


class TestTheMovedBaseIsAReviewableSituation:
    """The prompt's instructions, run against a repository whose base has moved.

    Substring assertions cannot tell a correct instruction from a plausible
    one. This builds the exact situation that aborted exec-3afef2976abe - the
    default branch advanced while the reviewed commit did not - and executes
    what the prompt tells the agent to do in it.
    """

    @pytest.fixture
    def workspace_with_a_moved_base(self, tmp_path: Path) -> tuple[Path, str]:
        """A fresh clone on the default branch, plus the head verify was told to review.

        Mirrors the real shape: `investigate` recorded base and head, then
        someone merged to main, then verify's workspace was provisioned - so
        the clone here is made AFTER the base moved, exactly as it would be.
        """
        origin = tmp_path / "origin"
        origin.mkdir()
        _git("init", "-b", "main", cwd=origin)
        recorded_base = _commit(origin, "base.py")

        _git("checkout", "-b", "fix/some-pr", cwd=origin)
        recorded_head = _commit(origin, "the-change-under-review.py")

        _git("checkout", "main", cwd=origin)
        base_now = _commit(origin, "someone-elses-merge.py")
        assert base_now != recorded_base, "the base did not move; the fixture proves nothing"

        workspace = tmp_path / "workspace"
        _git("clone", str(origin), str(workspace), cwd=tmp_path)
        assert _git("rev-parse", "HEAD", cwd=workspace).stdout.strip() == base_now
        return workspace, recorded_head

    def test_the_prompts_own_commands_reach_the_recorded_head(
        self, verify_prompt: str, workspace_with_a_moved_base: tuple[Path, str]
    ) -> None:
        workspace, recorded_head = workspace_with_a_moved_base

        block = next(
            (b for b in re.findall(r"```\n(.*?)```", verify_prompt, re.DOTALL) if "checkout" in b),
            None,
        )
        assert block is not None, "the prompt no longer shows the agent how to check anything out"

        for line in block.splitlines():
            instruction = line.split("#")[0].strip()
            if not instruction:
                continue
            assert instruction.startswith("git "), f"unexpected instruction {instruction!r}"
            _git(
                *(
                    recorded_head if arg == "<recorded-head-sha>" else arg
                    for arg in instruction.split()[1:]
                ),
                cwd=workspace,
            )

        assert _git("rev-parse", "HEAD", cwd=workspace).stdout.strip() == recorded_head, (
            "following the installed prompt on a moved base left the agent "
            "somewhere other than the commit it was told to review"
        )
