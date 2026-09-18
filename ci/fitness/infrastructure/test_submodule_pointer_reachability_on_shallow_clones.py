"""The reachability gate must answer correctly on the clone CI actually gives it (#1336).

`test_submodule_pointer_reachability` asks a real remote about the real `lib/`
pointers, so it can only ever be as right as this checkout is representative -
and a dev machine's clone is not. CI's is: `actions/checkout` runs
`git submodule update --depth=1`, which is both shallow and single-branch, and
on that shape the gate returned "this pointer has not been pushed" for four
pointers that were all merged. Every local reproduction passed, which is the
point - the bug lived in the difference.

So this builds that difference. Local repositories over `file://`, no network,
in the same order checkout uses: the default branch tip first, the pointer
second. A merged pointer must read as merged there, and an unmerged one must
still be refused - a fix that bought the first by giving up the second would
have removed the gate rather than repaired it.

`git branch -r --contains` is asserted on too. Under a single-branch refspec it
can name nothing, so the failure message degrades to "it has not been pushed" -
true of a commit that was pushed, and the opposite of the one fact the reader
needs. The message is most of this gate's value; it is worth a test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci.fitness.infrastructure.test_submodule_pointer_reachability import (
    Submodule,
    unmerged_pointer,
)

pytestmark = pytest.mark.architecture


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    (repo / "file.txt").write_text(message)
    _git("add", "file.txt", cwd=repo)
    _git("commit", "-m", message, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture
def upstream(tmp_path: Path) -> Path:
    """A submodule remote: three commits on `main`, one on a feature branch.

    `--bare` would refuse a working tree; a normal repo served over `file://`
    clones the same way and is far easier to build.
    """
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "gate@test", cwd=repo)
    _git("config", "user.name", "gate", cwd=repo)
    _commit(repo, "first")
    _commit(repo, "merged-pointer")
    _git("checkout", "-q", "-b", "feature/not-merged", cwd=repo)
    _commit(repo, "unmerged-pointer")
    _git("checkout", "-q", "main", cwd=repo)
    _commit(repo, "tip")
    return repo


def _superproject_with_ci_shaped_checkout(
    tmp_path: Path, upstream: Path, pointer: str
) -> Submodule:
    """A superproject whose submodule is checked out the way `actions/checkout` does.

    Shallow AND single-branch, tip fetched before the pointer. Both halves
    matter: the single-branch refspec blinds `branch -r --contains`, and the
    tip-first order is what leaves the pointer in a second graft fragment with
    no path to the tip.
    """
    root = tmp_path / "superproject"
    root.mkdir()
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "gate@test", cwd=root)
    _git("config", "user.name", "gate", cwd=root)

    url = f"file://{upstream}"
    path = "lib/thing"
    (root / ".gitmodules").write_text(
        f'[submodule "thing"]\n\tpath = {path}\n\turl = {url}\n'
    )

    worktree = root / path
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", "-q", "--depth=1", url, str(worktree), cwd=root)
    _git("fetch", "-q", "--depth=1", "origin", pointer, cwd=worktree)
    _git("checkout", "-q", pointer, cwd=worktree)

    # The gitlink is what merges, so write it directly rather than trusting the
    # working tree - `unmerged_pointer` reads `HEAD:<path>`, not the checkout.
    _git("update-index", "--add", "--cacheinfo", f"160000,{pointer},{path}", cwd=root)
    _git("add", ".gitmodules", cwd=root)
    _git("commit", "-q", "-m", "point at submodule", cwd=root)
    return Submodule(path=path, url=url, root=root)


def test_ci_shaped_checkout_is_actually_truncated(tmp_path: Path, upstream: Path) -> None:
    """The fixture reproduces the bug's preconditions, or it proves nothing.

    If a future git stops implying --single-branch, or checkout stops passing
    --depth, the tests below would pass on a fixture that no longer poses the
    question. They must fail here first instead.
    """
    merged = _git("rev-parse", "main~1", cwd=upstream)
    sub = _superproject_with_ci_shaped_checkout(tmp_path, upstream, merged)

    assert _git("rev-parse", "--is-shallow-repository", cwd=sub.worktree) == "true"
    assert (
        _git("config", "--get", "remote.origin.fetch", cwd=sub.worktree)
        == "+refs/heads/main:refs/remotes/origin/main"
    ), "clone is not single-branch, so it no longer reproduces CI's refspec"
    assert _git("rev-list", "--count", "origin/main", cwd=sub.worktree) == "1", (
        "origin/main is not truncated, so ancestry would be computable without the fix"
    )


def test_merged_pointer_passes_on_a_shallow_single_branch_clone(
    tmp_path: Path, upstream: Path
) -> None:
    """The false positive that failed all four submodules on #1337's own CI run."""
    merged = _git("rev-parse", "main~1", cwd=upstream)
    sub = _superproject_with_ci_shaped_checkout(tmp_path, upstream, merged)

    assert unmerged_pointer(sub) is None, (
        "a commit that is on main was reported as unmerged - the gate read a "
        "truncated graph as a verdict"
    )


def test_unmerged_pointer_is_still_refused_on_a_shallow_single_branch_clone(
    tmp_path: Path, upstream: Path
) -> None:
    """Deepening the clone must not cost the gate the refusal it exists for."""
    unmerged = _git("rev-parse", "feature/not-merged", cwd=upstream)
    sub = _superproject_with_ci_shaped_checkout(tmp_path, upstream, unmerged)

    problem = unmerged_pointer(sub)
    assert problem is not None, "a commit that is only on a feature branch was accepted"
    assert unmerged in problem, "the failure does not name the SHA"
    assert "lib/thing" in problem, "the failure does not name the submodule"
    assert "origin/feature/not-merged" in problem, (
        "the failure does not name the branch that DOES contain the commit, which "
        f"is the fact that tells a reader their submodule PR has not landed:\n{problem}"
    )
