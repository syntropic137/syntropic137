"""Running the gates must not modify the repository they are run from (#1343).

Several gates shell out to git, and the submodule-reachability gates build whole
git fixtures - `init`, `commit`, `checkout -b` - which belong inside a throwaway
repository under `tmp_path` and nowhere else. When one of them escapes, it
escapes into the developer's own checkout: commits named `first` and
`merged-pointer` in the real reflog, `main` force-moved off `origin/main`, a
stray `feature/not-merged`, files from other refs left untracked in the working
tree. One `.git` backs every worktree, so `main` moves for all of them, and the
next `git push origin main` pushes the fixture.

WHY THIS TEST IS SHAPED THE WAY IT IS
=====================================

**It asserts the property, not the outcome.** The run that did the damage above
reported 706 passed and "Invariant checks passed". Every gate was green while
the repository was being rewritten, so any test that asks "does the suite pass"
- including the gates' own assertions about their fixtures - was green
throughout and would have stayed green. The only thing that distinguishes the
two states is the one measured here: the invoking repository's refs, before and
after, byte for byte.

**It runs the gates against a repository built for the purpose.** Pointing them
at this checkout to find out whether they corrupt it is not a test of the bug,
it is the bug. `invoking_repository` is a real repository with real branches and
a real remote, which the child process is given as its ambient one, so an escape
lands there and is read back as a difference instead of as damage.

**It reproduces the environment the damage arrived through.** `GIT_DIR` is
exported to every hook git runs from a worktree; `.githooks/pre-push` runs `just
preflight`, and preflight runs this suite. `-C` and `cwd=` do not help, because
git reads `GIT_DIR` before either - which is why the two gates involved already
passed `cwd=` on every call and were corrupting the repository anyway. So the
child is launched the way the hook launches one, and both escape routes are
covered at once: a leaked `GIT_DIR`, and a call that names no directory at all
and so lands in the process's own.

**It runs the whole suite, not the two gates that were caught.** "Does not
modify the repository" is a property every gate owes, so the child is given this
directory and runs whatever is in it. Narrowing it to the modules that visibly
shell out to git would be cheaper and would have caught this bug - and would
have a hole in it, because a gate reaches git through whatever it imports as
readily as through its own `subprocess` call, and nothing about the import says
so. The population has to be the suite for the claim to be about the suite.

**No gate may sit the run out.** Every test module under this directory must
report tests in the child's own results. A module that collected nothing - an
import error, a marker rename - would quietly leave the population while the
claim about it stayed the same size, which is the "green over nothing" failure
this suite exists to refuse. It is also the only way this gate could pass by
doing no work at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_THIS_GATE = Path(__file__).resolve()
_SUITE = _THIS_GATE.parent
_ROOT = _SUITE.parents[1]

#: The whole suite runs in the child, including a networked gate that fetches
#: four submodules. Long enough for a cold link, short enough that a hung child
#: fails the build instead of occupying a runner.
_CHILD_TIMEOUT_SECONDS = 900


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _gates() -> list[Path]:
    """Every gate the child is expected to run: this suite, less this file.

    Less this file because it is the one that spawns the child, and a child that
    ran it would spawn another.
    """
    return sorted(path for path in _SUITE.rglob("test_*.py") if path.resolve() != _THIS_GATE)


def _refs(repo: Path) -> str:
    """Everything this repository points at, in a form a diff can be read from.

    Names as well as hashes: a gate that creates `feature/not-merged` has
    modified the repository just as surely as one that moves `main`, and the
    reader needs to see which.
    """
    return "\n".join(
        [
            "HEAD " + _git("rev-parse", "HEAD", cwd=repo),
            "HEAD -> " + _git("rev-parse", "--symbolic-full-name", "HEAD", cwd=repo),
            _git("for-each-ref", "--format=%(objectname) %(objecttype) %(refname)", cwd=repo),
        ]
    )


@pytest.fixture
def invoking_repository(tmp_path: Path) -> Path:
    """A stand-in for the checkout a developer runs the gates from.

    Branches, a remote and remote-tracking refs, because those are what got
    moved: a bare repository with one branch would still catch a stray commit
    but would not notice a fetch rewriting `refs/remotes/origin/*`.
    """
    remote = tmp_path / "origin.git"
    remote.mkdir()
    _git("init", "-q", "--bare", "-b", "main", cwd=remote)
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    _git("init", "-q", "-b", "main", cwd=checkout)
    _git("config", "user.email", "dev@test", cwd=checkout)
    _git("config", "user.name", "dev", cwd=checkout)
    (checkout / "README.md").write_text("the repository the gates are run from\n")
    _git("add", "README.md", cwd=checkout)
    _git("commit", "-q", "-m", "initial", cwd=checkout)
    _git("remote", "add", "origin", str(remote), cwd=checkout)
    _git("push", "-q", "origin", "main", cwd=checkout)
    _git("checkout", "-q", "-b", "fix/some-branch", cwd=checkout)
    return checkout


def _run_the_gates(repo: Path, report: Path) -> subprocess.CompletedProcess[str]:
    """Run the suite as the pre-push hook does: from `repo`, with `repo` as GIT_DIR.

    The child's exit code is deliberately not the subject. A gate that fails -
    for want of a network, or because it found a real violation - still owes the
    repository the same thing a passing one does, so the question asked
    afterwards is about the refs and not about the result.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_SUITE),
            "--ignore",
            str(_THIS_GATE),
            "-m",
            "architecture",
            "-q",
            "--tb=no",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
        ],
        cwd=repo,
        env={**os.environ, "GIT_DIR": str(repo / ".git")},
        capture_output=True,
        text=True,
        check=False,
        timeout=_CHILD_TIMEOUT_SECONDS,
    )


def _module_name(gate: Path) -> str:
    """The dotted name the child's own results record a gate under."""
    return ".".join(gate.relative_to(_ROOT).with_suffix("").parts)


def _gates_that_reported_no_tests(gates: list[Path], report: Path) -> list[Path]:
    """The gates the child has no result for, read from the results it wrote.

    Its results rather than its output, because output is where a crashed run
    looks like a quiet one. A module is answered for by `classname`, which is
    the dotted module for a bare test and `module.Class` for a method, so a
    gate counts as run when either shape names it.
    """
    if not report.exists():
        return list(gates)
    reported = {
        classname
        for case in ElementTree.parse(report).iter("testcase")
        if (classname := case.get("classname")) is not None
    }
    return [
        gate
        for gate in gates
        if not any(
            name == _module_name(gate) or name.startswith(f"{_module_name(gate)}.")
            for name in reported
        )
    ]


def test_running_the_gates_does_not_modify_the_invoking_repository(
    invoking_repository: Path, tmp_path: Path
) -> None:
    gates = _gates()
    assert gates, f"no gates found under {_SUITE}, so this would pass over nothing"

    before = _refs(invoking_repository)
    report = tmp_path / "gates.xml"
    child = _run_the_gates(invoking_repository, report)
    after = _refs(invoking_repository)

    silent = _gates_that_reported_no_tests(gates, report)
    assert not silent, (
        "these gates ran no tests, so nothing they do was measured here:\n  "
        + "\n  ".join(str(gate.relative_to(_ROOT)) for gate in silent)
        + "\nA gate that collects nothing is not evidence that it leaves the "
        "repository alone.\npytest said:\n" + child.stdout[-2000:] + child.stderr[-2000:]
    )

    assert after == before, (
        "running the fitness suite modified the repository it was run from.\n\n"
        f"before:\n{before}\n\nafter:\n{after}\n\n"
        "A gate built a git fixture in the repository it was invoked from instead "
        "of in its tmp_path. Naming the directory with -C or cwd= is not enough "
        "on its own: git resolves GIT_DIR first, and the pre-push hook exports it "
        "from every worktree. The repository-location variables are cleared for "
        "every test run in the root conftest.py - see _forget_the_ambient_"
        "repository there, and #1343."
    )
