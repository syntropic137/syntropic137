"""A submodule pointer must already be merged into that submodule's default branch (#1336).

Every other gate passes on a pointer that exists only on a feature branch of the
submodule repo: CI checks the submodule out by SHA, finds it, builds, goes green.
`check-submodules` asks whether the submodule is initialized and at its recorded
commit, which it is. Nothing asks the submodule's *remote* whether that commit is
reachable from the default branch. So merging leaves the superproject's main
pointing into an unmerged branch, and every fresh clone breaks the moment that
branch is deleted or rebased. #1329 is the live instance: green, unmergeable.

THE NETWORK QUESTION, DECIDED
=============================

**This check talks to the network, on purpose, and fails when it cannot.**

The property is "has the submodule change landed upstream", and upstream is the
only thing that knows. Every offline spelling of it measures the local clone
instead - which was populated by the very commit under test - so it would report
green over the exact state #1336 is about. There is no honest offline version of
this gate, only a reassuring one.

That is affordable because the gate it joins is already networked.
`fitness-invariants` runs inside `just preflight`, and `preflight` also runs
`check-default-workspace-image` (`docker pull` of the pinned image) and
`check-pinned-image-channels` (a registry query). Preflight has never been an
offline target, so this adds no new requirement to any environment that could
run it before. In CI it is owned by the `architectural-fitness` job in
`.github/workflows/ci.yml`, which checks out with `submodules: true` and runs
`just preflight`.

Consequently there is no skip in this file. A fetch that fails is a FAILED test
carrying git's own stderr, never a pass - a check that goes quiet exactly when it
cannot see is the "green gate over nothing" class the issue was filed about. The
one environment this cannot run in is an agent workspace container, where
`fitness` is already outside `preflight-agent` for want of a toolchain; nothing
new is hidden there.

Two deliberate deviations from the issue's sketch:

* the default branch is resolved with `ls-remote --symref`, not the local
  `origin/HEAD`. `origin/HEAD` is written once at clone time and never refreshed,
  so on a clone predating a default-branch rename it names a branch the remote no
  longer defaults to - and this gate's whole job is to not trust local state.
* the pointer is read from the superproject's stage-zero index entry, not from
  `git submodule status`. The index is the exact gitlink about to be committed
  and is identical to HEAD in CI; the checked-out submodule working tree can
  differ from both. Reading only HEAD made preflight reject every staged bump.

A SHALLOW SUBMODULE CLONE IS THE HARD CASE, AND CI ALWAYS HAS ONE
================================================================

An earlier revision of this file asserted that "a fetch that names no depth
deepens the refs it brings to full history". That is false, and it failed all
four submodules on this PR's own CI run while every pointer was in fact merged.
Two properties of `--depth=1` conspire, and a fix has to answer both:

* **the clone is single-branch.** `--depth=1` implies `--single-branch`, so the
  refspec is `+refs/heads/<default>:refs/remotes/origin/<default>` and no other
  remote branch is ever fetched. `git branch -r --contains` therefore cannot
  name a branch it was never given - the half of the failure message that tells
  a reader where their commit actually lives is structurally dead.
* **a plain fetch does not deepen.** `git submodule update --depth=1` takes the
  default branch tip first and the pointer second, so the client already holds
  what `fetch origin` would send. Nothing transfers, the shallow boundary
  stands, and the tip and the pointer sit in two grafted fragments with no path
  between them.

`merge-base --is-ancestor` then answers "not an ancestor" - not because the
commit is unmerged, but because the local graph has been truncated in a way that
makes ancestry unanswerable. Measured on a clone built the way checkout builds
one: `origin/main` held 1 commit, the answer was "unmerged", and the commit was
merged 9 commits back on main.

So the fetch here names a full refspec and unshallows. `_fetch_until_answerable`
owns both corrections, and the guard below owns the consequence that matters: a
truncation this gate failed to repair is reported as its own failure and never
as "not merged". "Cannot tell" and "no" must not reach a reader as one answer -
this is the same rule the network paragraph above states, applied to the local
graph instead of the remote. Do not replace that fetch with a bare
`fetch origin`: it is what #1337 shipped, and it rejects every pointer that is
not literally the tip of the default branch.

Scope: the direct submodules `.gitmodules` declares, matching `check-submodules`,
which is deliberately not `--recursive` because CI's own checkout leaves nested
submodules uninitialized. Widening either means changing the checkouts first.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).resolve().parents[3]

#: Long enough for a cold clone of the largest submodule over a slow link, short
#: enough that a hung gate fails the build instead of occupying a runner.
_NETWORK_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class Submodule:
    """One entry in `.gitmodules`, as the superproject declares it.

    `root` travels with the entry so the ancestry logic can be pointed at a
    superproject built by a test instead of only at this checkout. Without it
    the only way to exercise this gate is to mutate the real `lib/` pointers.
    """

    path: str
    url: str
    root: Path = _ROOT

    @property
    def worktree(self) -> Path:
        return self.root / self.path


def _git(
    *args: str, cwd: Path | None = None, timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or _ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def declared_submodules(root: Path = _ROOT) -> list[Submodule]:
    """Every submodule `.gitmodules` declares, read by git rather than parsed.

    `git config -f` because `.gitmodules` is git config syntax, not INI: it
    tolerates spellings configparser rejects, and a parser that disagrees with
    git about which submodules exist would skip one silently.
    """
    result = _git("config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$", cwd=root)
    assert result.returncode == 0, (
        f"could not read .gitmodules (git exit {result.returncode}):\n{result.stderr}"
    )

    submodules: list[Submodule] = []
    for line in result.stdout.splitlines():
        key, _, path = line.partition(" ")
        name = key[len("submodule.") : -len(".path")]
        url = _git("config", "-f", ".gitmodules", "--get", f"submodule.{name}.url", cwd=root)
        assert url.returncode == 0, f"submodule {name} declares a path but no url"
        submodules.append(Submodule(path=path, url=url.stdout.strip(), root=root))
    return submodules


def _default_branch(sub: Submodule) -> str:
    """The branch the remote itself calls default, asked fresh over the network."""
    result = _git(
        "ls-remote",
        "--symref",
        "origin",
        "HEAD",
        cwd=sub.worktree,
        timeout=_NETWORK_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"{sub.path}: cannot reach {sub.url} to ask for its default branch.\n"
        f"This gate is network-dependent by design and does not pass offline -\n"
        f"see this module's docstring. git said:\n{result.stderr}"
    )
    for line in result.stdout.splitlines():
        if line.startswith("ref:") and line.endswith("HEAD"):
            return line.split()[1].removeprefix("refs/heads/")
    pytest.fail(f"{sub.path}: {sub.url} reports no default branch (empty repository?)")


#: A `--depth=1` clone is single-branch, so its configured refspec fetches only
#: the default branch. Naming the full refspec explicitly is what lets
#: `branch -r --contains` answer "it is on: <branch>" at all.
_ALL_BRANCHES = "+refs/heads/*:refs/remotes/origin/*"


def _is_shallow(sub: Submodule) -> bool:
    return _git("rev-parse", "--is-shallow-repository", cwd=sub.worktree).stdout.strip() == "true"


def _fetch_until_answerable(sub: Submodule) -> subprocess.CompletedProcess[str]:
    """Bring down enough of the remote that ancestry is a question git can answer.

    A caller only needs to know that afterwards the local graph either supports
    the ancestry query or the attempt failed loudly - not which of the two
    truncations of a CI checkout had to be undone, or in which order.

    --prune so a branch deleted upstream stops being reported as one that
    contains the commit. That is not cosmetic: "deleted or rebased" is the
    failure this gate exists to predict, and a stale remote-tracking ref would
    answer with the state of the world before it happened.

    --unshallow only when the clone is shallow, because git refuses it on a
    complete repository. It is the expensive line here - it is also the only one
    that restores the commits between the pointer and the branch tip, which are
    exactly the commits ancestry is made of. Measured at ~2s for the largest
    submodule; a wrong answer costs a broken clone for whoever clones next.
    """
    depth = ["--unshallow"] if _is_shallow(sub) else []
    return _git(
        "fetch",
        "--prune",
        *depth,
        "origin",
        _ALL_BRANCHES,
        cwd=sub.worktree,
        timeout=_NETWORK_TIMEOUT_SECONDS,
    )


def _containing_branches(sub: Submodule, pointer: str) -> list[str]:
    """Which remote branches hold this commit. Local: the fetch already ran."""
    result = _git("branch", "-r", "--contains", pointer, cwd=sub.worktree)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if "->" not in line]


def unmerged_pointer(sub: Submodule) -> str | None:
    """Why this submodule's pointer must not merge yet, or None when it may.

    The string is the whole point of the check. "Not an ancestor" tells a reader
    that something is wrong; naming the SHA and the branches that DO hold it
    tells them the actual fact, which is that their submodule PR has not landed.

    Returning None means the pointer is reachable. It never means "could not
    tell": failing to reach the remote raises, because those two must not arrive
    at the caller as the same answer.
    """
    worktree = sub.worktree
    if not (worktree / ".git").exists():
        return (
            f"{sub.path} is not checked out, so its pointer cannot be verified "
            f"against {sub.url}.\nRun: just submodules-init"
        )

    pointer = _git("ls-files", "--stage", "--", sub.path, cwd=sub.root)
    fields = pointer.stdout.split()
    assert pointer.returncode == 0 and len(fields) >= 4, (
        f"{sub.path}: no stage-zero index entry:\n{pointer.stderr}"
    )
    assert fields[0] == "160000" and fields[2] == "0", (
        f"{sub.path}: index entry is not a stage-zero gitlink: {pointer.stdout.strip()}"
    )
    sha = fields[1]

    branch = _default_branch(sub)
    fetch = _fetch_until_answerable(sub)
    assert fetch.returncode == 0, (
        f"{sub.path}: cannot fetch {sub.url}, so reachability is unknown.\n"
        f"This gate is network-dependent by design and does not pass offline -\n"
        f"see this module's docstring. git said:\n{fetch.stderr}"
    )

    # A truncated graph answers "not an ancestor" for a merged commit, so these
    # two must fail as themselves. Reporting either as "not merged" would be a
    # confident wrong answer, which is worse than the silence this gate refuses.
    assert not _is_shallow(sub), (
        f"{sub.path}: still a shallow clone after fetching {sub.url}, so ancestry\n"
        "is not computable and this gate cannot answer. This is a bug in the gate,\n"
        "not a verdict on the pointer - see this module's docstring."
    )
    tip = _git("rev-parse", "--verify", f"refs/remotes/origin/{branch}", cwd=worktree)
    assert tip.returncode == 0, (
        f"{sub.path}: fetched {sub.url} but have no origin/{branch} to compare against,\n"
        f"so ancestry is not computable and this gate cannot answer. git said:\n{tip.stderr}"
    )

    if _git("merge-base", "--is-ancestor", sha, f"origin/{branch}", cwd=worktree).returncode == 0:
        return None

    if _git("cat-file", "-e", f"{sha}^{{commit}}", cwd=worktree).returncode != 0:
        whereabouts = (
            f"  {sha} does not exist on {sub.url} at all.\n"
            "  It was never pushed, or it has been rebased away and garbage collected."
        )
    elif branches := _containing_branches(sub, sha):
        whereabouts = "  it is on: " + ", ".join(branches)
    else:
        whereabouts = f"  no branch on {sub.url} contains it - it has not been pushed."

    return (
        f"{sub.path} points at a commit that is not on {branch}.\n"
        f"  pointer: {sha}\n"
        f"  remote:  {sub.url}\n"
        f"{whereabouts}\n"
        "\n"
        "The submodule change has not merged yet. Merging this would leave the\n"
        "superproject's main pointing into an unmerged branch, which breaks every\n"
        "fresh clone the moment that branch is deleted or rebased.\n"
        "\n"
        "Land the submodule PR first, then re-point at the merged commit:\n"
        f"  git -C {sub.path} fetch origin && git -C {sub.path} checkout origin/{branch}\n"
        f"  git add {sub.path}"
    )


@pytest.mark.parametrize("sub", declared_submodules(), ids=lambda s: s.path)
def test_submodule_pointer_is_reachable_from_its_default_branch(sub: Submodule) -> None:
    problem = unmerged_pointer(sub)
    assert problem is None, problem


def test_every_declared_submodule_is_actually_checked() -> None:
    """The parametrization is the population; an empty one would pass silently.

    A `.gitmodules` that fails to parse, or a rename of the `path` key, would
    yield zero cases and a green run over nothing - the failure mode this whole
    file exists to refuse.
    """
    declared = declared_submodules()
    assert declared, ".gitmodules declares no submodules, so this gate checks nothing"
    assert {s.path for s in declared} == {
        line.split()[1] for line in _git("submodule", "status").stdout.splitlines()
    }, "the submodules git reports and the ones .gitmodules declares disagree"
