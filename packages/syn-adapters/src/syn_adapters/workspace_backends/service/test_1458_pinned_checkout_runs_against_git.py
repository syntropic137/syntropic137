"""The pinned checkout, run by a real git against a real origin (#1458).

`test_1458_a_resume_is_provisioned_at_its_parents_commits` (syn-domain) proves a
resume's recorded commit reaches the setup script. This proves what that script
then does with it, which a substring assertion cannot: the generated script is
run under bash with the real git, against a local bare repository standing in
for GitHub through `url.<file>.insteadOf`. Nothing else is rewritten except the
hardcoded `/workspace` prefix, since the tests do not run as root.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.service.setup_phase_secrets import (
    PINNED_COMMIT_UNREACHABLE_EXIT_CODE,
    SetupPhaseSecrets,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("git") is None, reason="needs a real git"),
]

REPO = "org/pinned"


def _git(*args: str, cwd: Path, env: dict[str, str]) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


class _Origin:
    """A bare repository served as ``https://github.com/org/pinned``."""

    def __init__(self, tmp_path: Path) -> None:
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.workspace = tmp_path / "ws"
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        remotes = tmp_path / "remotes"
        self.bare = remotes / REPO
        self.bare.mkdir(parents=True)
        _git("init", "--quiet", "--bare", "--initial-branch=main", cwd=self.bare, env=self.env)
        _git(
            "config",
            "--global",
            f"url.file://{remotes}/.insteadOf",
            "https://github.com/",
            cwd=tmp_path,
            env=self.env,
        )
        self.work = tmp_path / "author"
        _git("clone", "--quiet", str(self.bare), str(self.work), cwd=tmp_path, env=self.env)
        _git("checkout", "--quiet", "-b", "main", cwd=self.work, env=self.env)

    def commit(self, message: str, *, branch: str = "main") -> str:
        _git("checkout", "--quiet", "-B", branch, cwd=self.work, env=self.env)
        _git("commit", "--quiet", "--allow-empty", "-m", message, cwd=self.work, env=self.env)
        _git("push", "--quiet", "--force", "origin", branch, cwd=self.work, env=self.env)
        return _git("rev-parse", "HEAD", cwd=self.work, env=self.env)

    def delete_branch(self, branch: str) -> None:
        _git("push", "--quiet", "origin", "--delete", branch, cwd=self.work, env=self.env)

    def provision(self, pinned: dict[str, str]) -> subprocess.CompletedProcess[str]:
        secrets = SetupPhaseSecrets.for_testing(
            repositories=[f"https://github.com/{REPO}"], pinned_commits=pinned
        )
        script = secrets.build_setup_script().replace("/workspace", str(self.workspace))
        return subprocess.run(["bash", "-c", script], env=self.env, capture_output=True, text=True)

    def head(self) -> str:
        return _git("rev-parse", "HEAD", cwd=self.workspace / "repos" / "pinned", env=self.env)

    def tag(self, name: str, sha: str) -> None:
        _git("tag", name, sha, cwd=self.work, env=self.env)
        _git("push", "--quiet", "origin", name, cwd=self.work, env=self.env)

    def unpushed(self) -> str:
        """What the unpushed-work guard would read as this phase's own work."""
        return _git(
            "rev-list",
            "HEAD",
            "--not",
            "--remotes",
            cwd=self.workspace / "repos" / "pinned",
            env=self.env,
        )


@pytest.fixture
def origin(tmp_path: Path) -> _Origin:
    return _Origin(tmp_path)


class TestAPinnedRepositoryIsCheckedOutAtItsCommit:
    def test_an_older_commit_on_the_default_branch(self, origin: _Origin) -> None:
        """The case #1458 is about: `main` moved on after the parent started."""
        pinned = origin.commit("what the parent ran on")
        moved_on = origin.commit("landed after the parent started")

        run = origin.provision({REPO: pinned})

        assert run.returncode == 0, run.stderr
        assert origin.head() == pinned
        assert origin.head() != moved_on

    def test_a_commit_only_another_branch_contains(self, origin: _Origin) -> None:
        origin.commit("main")
        pinned = origin.commit("only on the feature branch", branch="feature")

        run = origin.provision({REPO: pinned})

        assert run.returncode == 0, run.stderr
        assert origin.head() == pinned

    def test_a_commit_only_a_tag_retains_after_a_force_push(self, origin: _Origin) -> None:
        """Origin still publishes it, so it is checked out, not refused."""
        base = origin.commit("base")
        pinned = origin.commit("tagged, then force-pushed off main")
        origin.tag("retained", pinned)
        _git("reset", "--quiet", "--hard", base, cwd=origin.work, env=origin.env)
        origin.commit("rewritten history")

        run = origin.provision({REPO: pinned})

        assert run.returncode == 0, run.stderr
        assert origin.head() == pinned

    def test_an_inherited_commit_is_never_read_as_unpushed_work(self, origin: _Origin) -> None:
        """`--not --remotes` covers the pin, whether a branch or only a tag holds it."""
        origin.commit("base")
        on_branch = origin.commit("still on main")
        tagged = origin.commit("only a tag keeps this")
        origin.tag("retained", tagged)
        _git("reset", "--quiet", "--hard", on_branch, cwd=origin.work, env=origin.env)
        _git("push", "--quiet", "--force", "origin", "main", cwd=origin.work, env=origin.env)

        for pinned in (on_branch, tagged):
            shutil.rmtree(origin.workspace, ignore_errors=True)
            run = origin.provision({REPO: pinned})

            assert run.returncode == 0, run.stderr
            assert origin.head() == pinned
            assert origin.unpushed() == ""

    def test_without_a_pin_the_default_branch_head_is_unchanged(self, origin: _Origin) -> None:
        origin.commit("older")
        head = origin.commit("head of main")

        run = origin.provision({})

        assert run.returncode == 0, run.stderr
        assert origin.head() == head


class TestAnUnreachableCommitIsRefusedNotReplaced:
    """Never run on code the parent did not: no fallback to the default branch."""

    def test_a_commit_whose_branch_was_deleted(self, origin: _Origin) -> None:
        origin.commit("main")
        pinned = origin.commit("on a branch that is later deleted", branch="gone")
        origin.delete_branch("gone")

        run = origin.provision({REPO: pinned})

        assert run.returncode == PINNED_COMMIT_UNREACHABLE_EXIT_CODE
        assert f"{REPO} cannot be provisioned at its recorded commit {pinned}" in run.stderr

    def test_a_commit_force_pushed_off_its_branch(self, origin: _Origin) -> None:
        base = origin.commit("base")
        pinned = origin.commit("force-pushed away")
        _git("reset", "--quiet", "--hard", base, cwd=origin.work, env=origin.env)
        origin.commit("rewritten history")

        run = origin.provision({REPO: pinned})

        assert run.returncode == PINNED_COMMIT_UNREACHABLE_EXIT_CODE
        assert pinned in run.stderr

    def test_a_commit_origin_never_had(self, origin: _Origin) -> None:
        origin.commit("main")
        never = "0" * 40

        run = origin.provision({REPO: never})

        assert run.returncode == PINNED_COMMIT_UNREACHABLE_EXIT_CODE
        assert never in run.stderr


class TestOnlyAFullCommitIdIsEverInterpolated:
    """The sha lands in bash, so a value that is not one never renders a script."""

    @pytest.mark.parametrize(
        "sha", ["main", "abc123", "A" * 40, "$(touch /tmp/x)" + "0" * 26, "0" * 41]
    )
    def test_anything_else_is_rejected(self, sha: str) -> None:
        secrets = SetupPhaseSecrets.for_testing(
            repositories=[f"https://github.com/{REPO}"], pinned_commits={REPO: sha}
        )

        with pytest.raises(ValueError, match="full commit id"):
            secrets.build_setup_script()
