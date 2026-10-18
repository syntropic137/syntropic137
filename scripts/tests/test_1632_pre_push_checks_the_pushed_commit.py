"""`.githooks/pre-push` preflights the commit being pushed, not the worktree (#1632).

The hook used to run `just preflight` on whatever was checked out and ignore
the refs git hands it on stdin. `git push origin <sha>:branch` from a stale
checkout, or a push with uncommitted edits, then validated a tree the remote
never receives: it could fail a good commit or pass a bad one.

These tests push for real, from a throwaway repository to a bare remote, with
the hook wired through `core.hooksPath` and `just` stubbed on PATH. The stub
records what preflight would have checked - the commit checked out where it
ran, and whether that tree carried the uncommitted edit - so each assertion is
about what the consumer of the hook's decision actually saw.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

HOOKS = Path(__file__).resolve().parents[2] / ".githooks"

# Runs plain `git` with whatever environment the hook gave it, so a leaked
# GIT_DIR would show up here as the outer checkout's HEAD.
JUST_STUB = """#!/usr/bin/env bash
set -euo pipefail
[ "$1" = preflight ] || exit 64
dirty=clean; [ -e dirty.txt ] && dirty=dirty
echo "$(git rev-parse HEAD) $PWD $dirty" >> "$TRACE"
[ ! -e "$FAIL_ON" ] || ! grep -q bad payload.txt
"""


class Repo:
    def __init__(self, root: Path) -> None:
        self.dir = root / "work"
        self.remote = root / "remote.git"
        self.trace = root / "trace"
        self.fail_on = root / "fail_on_bad"
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "just"
        stub.write_text(JUST_STUB)
        stub.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "TRACE": str(self.trace),
            "FAIL_ON": str(self.fail_on),
            "TMPDIR": str(root),
        }
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        self.dir.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("remote", "add", "origin", str(self.remote))

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.dir, env=self.env, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, payload: str) -> str:
        (self.dir / "payload.txt").write_text(payload)
        self.git("add", "payload.txt")
        self.git("commit", "-q", "-m", payload)
        return self.git("rev-parse", "HEAD")

    def arm_hook(self) -> None:
        self.git("config", "core.hooksPath", str(HOOKS))

    def push(
        self, *refspecs: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "push", "origin", *refspecs],
            cwd=self.dir,
            env={**self.env, **(env or {})},
            capture_output=True,
            text=True,
        )

    def checked(self) -> list[tuple[str, str, str]]:
        if not self.trace.exists():
            return []
        rows = [line.split(" ") for line in self.trace.read_text().splitlines()]
        return [(sha, where, dirty) for sha, where, dirty in rows]

    def worktrees(self) -> list[str]:
        return [
            line
            for line in self.git("worktree", "list", "--porcelain").splitlines()
            if line.startswith("worktree ")
        ]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def test_a_clean_head_is_checked_in_place(repo: Repo) -> None:
    head = repo.commit("one")
    repo.arm_hook()

    result = repo.push("main")

    assert result.returncode == 0, result.stderr
    assert repo.checked() == [(head, str(repo.dir), "clean")]


def test_pushing_an_older_sha_checks_that_sha_not_the_checkout(repo: Repo) -> None:
    old = repo.commit("one")
    head = repo.commit("two")
    repo.arm_hook()

    result = repo.push(f"{old}:refs/heads/stale")

    assert result.returncode == 0, result.stderr
    [(sha, where, _)] = repo.checked()
    assert sha == old != head
    assert where != str(repo.dir)
    assert repo.git("rev-parse", "HEAD") == head
    assert len(repo.worktrees()) == 1, "the temporary worktree was left behind"


def test_a_git_dir_exported_to_the_hook_does_not_redirect_the_worktree(repo: Repo) -> None:
    """Newer git exports GIT_DIR to hooks; inherited, it overrides cwd."""
    old = repo.commit("one")
    repo.commit("two")
    repo.arm_hook()

    result = repo.push(f"{old}:refs/heads/stale", env={"GIT_DIR": str(repo.dir / ".git")})

    assert result.returncode == 0, result.stderr
    assert [sha for sha, _, _ in repo.checked()] == [old]


def test_a_bad_pushed_sha_is_refused_even_when_the_checkout_is_good(repo: Repo) -> None:
    bad = repo.commit("bad")
    repo.commit("good")
    repo.fail_on.touch()
    repo.arm_hook()

    result = repo.push(f"{bad}:refs/heads/stale")

    assert result.returncode != 0
    assert [sha for sha, _, _ in repo.checked()] == [bad]
    assert repo.git("ls-remote", "origin") == ""
    assert len(repo.worktrees()) == 1, "a failing preflight left its worktree behind"


def test_uncommitted_edits_are_not_what_gets_checked(repo: Repo) -> None:
    head = repo.commit("bad")
    repo.fail_on.touch()
    # The edit would make the checkout pass; the commit being pushed does not.
    (repo.dir / "payload.txt").write_text("fixed but not committed")
    (repo.dir / "dirty.txt").write_text("untracked")
    repo.arm_hook()

    result = repo.push("main")

    assert result.returncode != 0
    [(sha, where, dirty)] = repo.checked()
    assert (sha, dirty) == (head, "clean")
    assert where != str(repo.dir)


def test_every_distinct_pushed_commit_is_checked_once(repo: Repo) -> None:
    old = repo.commit("one")
    head = repo.commit("two")
    repo.arm_hook()

    result = repo.push(f"{old}:refs/heads/a", "main", "main:refs/heads/b")

    assert result.returncode == 0, result.stderr
    assert sorted(sha for sha, _, _ in repo.checked()) == sorted([old, head])


def test_a_delete_runs_no_preflight(repo: Repo) -> None:
    repo.commit("one")
    repo.push("main:refs/heads/doomed")
    repo.arm_hook()

    result = repo.push(":refs/heads/doomed")

    assert result.returncode == 0, result.stderr
    assert repo.checked() == []
