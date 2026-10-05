"""Checking a cloned repository out at the commit its run pinned it to (#1458).

The setup script clones each repository at its default branch. An execution
must instead run on the commits it recorded - a resume, on its parent's - so
for every repository with a recorded commit this module appends the lines
that verify origin still publishes that commit, check it out detached, or end
the script with `PINNED_COMMIT_UNREACHABLE_EXIT_CODE` refusing to run on
anything else.

A phase that CONTINUES a branch (#1513) - a resume's resumed phase picking up
the branch its parent's attempt pushed - is checked out ON that branch at its
head instead of detached, so its next push lands on the parent's PR. Its pin
is the head the resume recorded; the branch must still contain it.

`SetupPhaseSecrets` decides WHICH repositories are pinned and where they are
cloned; everything about HOW a pin is honoured, or refused, lives here.
"""

from __future__ import annotations

import re
import shlex
from typing import Final

#: The setup script's exit status when a repository cannot be checked out at
#: the commit it was pinned to (#1458). sysexits' EX_DATAERR - the input named
#: something that is not there - and a status neither git (1, 128, 129) nor
#: bash (126, 127, 128+n) uses, so the provisioning handler can tell this
#: refusal from every other way setup fails without reading its output.
PINNED_COMMIT_UNREACHABLE_EXIT_CODE: Final = 65

#: A full commit id, SHA-1 or SHA-256. Checked before it is written into the
#: script: the value names a revision on a git command line, and a value that
#: began with `-` would be read there as an option.
_COMMIT_ID_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

#: Where a pin no origin BRANCH contains is recorded once it is checked out, so
#: `--remotes` covers it. A remote of its own rather than `origin/...`, so it
#: can never be read as one of origin's branches; keyed by the sha, which no
#: branch is ever named.
_PIN_REMOTE_REF: Final = "refs/remotes/pinned"

#: A branch name safe to write on a git command line: no leading `-`, nothing
#: a shell or a refspec would read as syntax. Quoted as well; this is the
#: refusal for a name no push could have created in the first place.
_BRANCH_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]*")


#: The refusal line every pin writes, in both variants: ``dest`` and ``sha``.
_PIN_LINE_RE = re.compile(
    r"git -C (\S+) cat-file -e ([0-9a-f]{64}|[0-9a-f]{40})\^\{commit\} 2>/dev/null; then"
)


def pinned_heads(script: str) -> dict[str, str]:
    """Clone directory -> the commit ``script`` checks it out at (#967).

    The reverse of `append_pinned_checkout`, kept beside it so the two cannot
    drift: what a workspace that ran ``script`` successfully reports as each
    pinned repository's HEAD. For a backend that runs no script - the
    in-memory test double - and must still answer as one that did.
    """
    return {shlex.split(dest)[0]: sha for dest, sha in _PIN_LINE_RE.findall(script)}


def append_pinned_checkout(
    lines: list[str], *, repository: str, dest: str, sha: str, branch: str | None = None
) -> None:
    """Check ``dest`` out at ``sha``, or end the setup script refusing to (#1458).

    THE COMMIT MUST STILL BE SOMEWHERE ORIGIN PUBLISHES IT - a branch or a
    tag - not merely exist. The clone above is a full one, which fetches every
    branch and every tag, so a commit present after it is one origin still
    retains, and a commit absent from it is one nothing on origin reaches:
    force-pushed away, or its branch deleted. That absence is the refusal.
    Fetching it by id instead - GitHub often still serves it - is not tried:
    nothing retains it, so the next phase of the same run could find it
    collected, and two phases of one run would disagree about what it ran on.

    A commit only a TAG retains is accepted (a release tag outliving a
    force-push is the ordinary case), but `--remotes`, which the unpushed-work
    guard and branch observation both subtract, holds branches only, so HEAD
    there would read as work this phase made and never pushed. For that case
    alone the pin is recorded as `_PIN_REMOTE_REF`, under `refs/remotes`
    because origin does hold it; a commit some branch contains needs nothing.

    NEVER A FALLBACK TO THE DEFAULT BRANCH. A run's recorded commit is the
    code it ran on, and a resume of it runs the rest of the same work on that
    code; a phase that quietly ran elsewhere would make the record a lie.
    The refusal names the repository and the commit, and exits with
    `PINNED_COMMIT_UNREACHABLE_EXIT_CODE` so it is told apart without parsing.

    Detached, because the commit is a point in history and not a branch: the
    phase branches from it as it would have branched from the default branch.
    Runs BEFORE the submodule step, so submodules follow this commit's
    gitlinks rather than the default branch's.

    ON A BRANCH when ``branch`` is given (#1513): the phase continues that
    branch, so it is checked out at ``origin/<branch>``'s head, tracking it.
    The head must still contain ``sha`` - the head the resume confirmed - or
    the branch was force-pushed since and the phase is refused exactly as an
    unreachable commit is, never run on a rewritten branch.

    Raises:
        ValueError: ``sha`` is not a full commit id, or ``branch`` is not a
            plain branch name.
    """
    if not _COMMIT_ID_RE.fullmatch(sha):
        msg = f"The recorded commit of {repository} is not a full commit id: {sha!r}"
        raise ValueError(msg)
    repo = shlex.quote(dest)
    refusal = (
        f"ERROR: {repository} cannot be provisioned at its recorded commit {sha}:"
        " no branch or tag of origin reaches it (force-pushed away, or its branch deleted)."
        " Refusing to run this phase on different code (#1458)."
    )
    lines.append(
        f"if ! git -C {repo} cat-file -e {sha}^{{commit}} 2>/dev/null; then"
        f" printf '%s\\n' {shlex.quote(refusal)} >&2;"
        f" exit {PINNED_COMMIT_UNREACHABLE_EXIT_CODE}; fi"
    )
    if branch is not None:
        _append_branch_checkout(lines, repository=repository, repo=repo, sha=sha, branch=branch)
        return
    lines.append(
        f'[ -n "$(git -C {repo} branch -r --contains {sha} 2>/dev/null)" ]'
        f" || git -C {repo} update-ref {_PIN_REMOTE_REF}/{sha} {sha}"
    )
    lines.append(f"git -C {repo} -c advice.detachedHead=false checkout --quiet --detach {sha}")


def _append_branch_checkout(
    lines: list[str], *, repository: str, repo: str, sha: str, branch: str
) -> None:
    """Check ``repo`` out on ``branch`` at origin's head of it, which must contain ``sha``."""
    if not _BRANCH_RE.fullmatch(branch) or ".." in branch:
        msg = f"The continued branch of {repository} is not a plain branch name: {branch!r}"
        raise ValueError(msg)
    remote = shlex.quote(f"refs/remotes/origin/{branch}")
    name = shlex.quote(branch)
    refusal = (
        f"ERROR: {repository} cannot continue branch {branch}: origin no longer has it at"
        f" or after {sha} (deleted or force-pushed since the resume started)."
        " Refusing to run this phase on a rewritten branch (#1513)."
    )
    lines.append(
        f"if ! git -C {repo} merge-base --is-ancestor {sha} {remote} 2>/dev/null; then"
        f" printf '%s\\n' {shlex.quote(refusal)} >&2;"
        f" exit {PINNED_COMMIT_UNREACHABLE_EXIT_CODE}; fi"
    )
    lines.append(f"git -C {repo} checkout --quiet -B {name} {remote}")
    lines.append(f"git -C {repo} branch --quiet --set-upstream-to=origin/{branch} {name}")
