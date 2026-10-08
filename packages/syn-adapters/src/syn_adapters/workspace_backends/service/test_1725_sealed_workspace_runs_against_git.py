"""A workspace sealed at its pin, run by a real git against a real origin (#1725).

An eval agent provisioned at the first parent of a fix must not be able to
read the fix. The generated setup script is run under bash with the real git
against a local bare repository standing in for GitHub (the harness of
`test_1458_pinned_checkout_runs_against_git`), and the agent's own probes -
`git log --all`, `git show <fix>`, `git fetch origin`, the credential file -
are then run in the result. The unsealed control proves each probe WOULD find
the fix, so a green sealed run is a finding and not an absence of one.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_adapters.workspace_backends.service.test_1458_pinned_checkout_runs_against_git import (
    REPO,
    _git,
    _Origin,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("git") is None, reason="needs a real git"),
]


class _Case:
    """An origin whose default branch, a tag and a branch all hold the fix."""

    def __init__(self, tmp_path: Path) -> None:
        self.origin = _Origin(tmp_path)
        work = self.origin.work
        (work / "pinned.txt").write_text("the code the task is set on\n")
        _git("add", "pinned.txt", cwd=work, env=self.origin.env)
        self.pin = self.origin.commit("the first parent of the fix")
        self.fix = self.origin.commit("THE FIX")
        self.origin.tag("v-after-the-fix", self.fix)
        self.later_branch = self.origin.commit("further work", branch="later")
        self.repo = self.origin.workspace / "repos" / "pinned"

    def provision(self, *, sealed: bool) -> subprocess.CompletedProcess[str]:
        secrets = SetupPhaseSecrets.for_testing(
            repositories=[f"https://github.com/{REPO}"],
            repo_tokens={f"https://github.com/{REPO}": "tok-installation"},
            pinned_commits={REPO: self.pin},
            sealed_at_pin=sealed,
        )
        script = secrets.build_setup_script().replace("/workspace", str(self.origin.workspace))
        return subprocess.run(
            ["bash", "-c", script], env=self.origin.env, capture_output=True, text=True
        )

    def probe(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.origin.env, capture_output=True, text=True
        )

    def every_reachable_commit(self) -> set[str]:
        return set(self.probe("log", "--all", "--reflog", "--format=%H").stdout.split())


@pytest.fixture
def case(tmp_path: Path) -> _Case:
    return _Case(tmp_path)


class TestTheUnsealedWorkspaceLeaksTheFix:
    """The control: without the seal, every probe below finds the answer."""

    def test_every_probe_reaches_the_fix(self, case: _Case) -> None:
        run = case.provision(sealed=False)

        assert run.returncode == 0, run.stderr
        assert case.fix in case.every_reachable_commit()
        assert case.probe("cat-file", "-e", f"{case.fix}^{{commit}}").returncode == 0
        assert case.probe("fetch", "--quiet", "origin").returncode == 0
        assert (case.origin.home / ".git-credentials").exists()


class TestASealedWorkspaceCannotReachTheFix:
    def test_the_pinned_files_are_present_at_the_pin(self, case: _Case) -> None:
        run = case.provision(sealed=True)

        assert run.returncode == 0, run.stderr
        assert case.probe("rev-parse", "HEAD").stdout.strip() == case.pin
        assert (case.repo / "pinned.txt").read_text() == "the code the task is set on\n"

    def test_no_ref_reflog_or_tag_reaches_past_the_pin(self, case: _Case) -> None:
        case.provision(sealed=True)

        reachable = case.every_reachable_commit()
        assert case.pin in reachable
        assert case.fix not in reachable
        assert case.later_branch not in reachable
        assert case.probe("tag").stdout.strip() == ""

    def test_a_known_later_commit_id_resolves_to_nothing(self, case: _Case) -> None:
        """An agent that read the fix's sha somewhere still cannot show it."""
        case.provision(sealed=True)

        assert case.probe("cat-file", "-e", f"{case.fix}^{{commit}}").returncode != 0
        assert not (case.repo / ".git" / "FETCH_HEAD").exists()

    def test_there_is_no_remote_to_fetch_from(self, case: _Case) -> None:
        case.provision(sealed=True)

        assert case.probe("remote").stdout.strip() == ""
        assert case.probe("fetch", "origin").returncode != 0
        assert case.fix not in case.every_reachable_commit()

    def test_no_github_credential_survives_setup(self, case: _Case) -> None:
        case.provision(sealed=True)

        home = case.origin.home
        assert not (home / ".git-credentials").exists()
        assert not (home / ".config" / "gh" / "hosts.yml").exists()
        helper = subprocess.run(
            ["git", "config", "--global", "--get-all", "credential.helper"],
            env=case.origin.env,
            capture_output=True,
            text=True,
        )
        assert helper.stdout.strip() == ""

    def test_the_unpushed_work_guard_reads_nothing_inherited(self, case: _Case) -> None:
        case.provision(sealed=True)

        assert case.origin.unpushed() == ""


class TestAWorkspaceThatCannotBeSealedIsRefused:
    def test_an_unpinned_repository(self) -> None:
        with pytest.raises(ValueError, match="unpinned"):
            SetupPhaseSecrets.for_testing(
                repositories=[f"https://github.com/{REPO}"], sealed_at_pin=True
            )

    def test_a_continued_branch(self) -> None:
        with pytest.raises(ValueError, match="continued"):
            SetupPhaseSecrets.for_testing(
                repositories=[f"https://github.com/{REPO}"],
                pinned_commits={REPO: "a" * 40},
                continued_branches={REPO: "feature"},
                sealed_at_pin=True,
            )

    def test_gh_is_given_no_credential(self) -> None:
        secrets = SetupPhaseSecrets.for_testing(
            repositories=[f"https://github.com/{REPO}"],
            repo_tokens={f"https://github.com/{REPO}": "tok"},
            pinned_commits={REPO: "a" * 40},
            sealed_at_pin=True,
        )

        assert secrets.gh_token is None
        assert "hosts.yml" not in secrets.build_setup_script().split("# Seal")[0]

    def test_without_a_clone_there_is_nothing_to_seal_and_still_no_credential(self) -> None:
        secrets = SetupPhaseSecrets.for_testing(
            repositories=[f"https://github.com/{REPO}"],
            repo_tokens={f"https://github.com/{REPO}": "tok"},
            clone_repos=False,
            sealed_at_pin=True,
        )
        script = secrets.build_setup_script()

        assert "git remote remove" not in script
        assert "oauth_token:" not in script
        assert "rm -f ~/.git-credentials ~/.config/gh/hosts.yml" in script
