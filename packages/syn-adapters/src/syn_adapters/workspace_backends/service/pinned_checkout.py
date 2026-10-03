"""Checking a cloned repository out at the commit its run pinned it to (#1458).

The setup script clones each repository at its default branch. An execution
must instead run on the commits it recorded - a resume, on its parent's - so
for every repository with a recorded commit this module appends the lines
that verify origin still publishes that commit, check it out detached, or end
the script with `PINNED_COMMIT_UNREACHABLE_EXIT_CODE` refusing to run on
anything else.

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


def append_pinned_checkout(lines: list[str], *, repository: str, dest: str, sha: str) -> None:
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

    Raises:
        ValueError: ``sha`` is not a full commit id.
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
    lines.append(
        f'[ -n "$(git -C {repo} branch -r --contains {sha} 2>/dev/null)" ]'
        f" || git -C {repo} update-ref {_PIN_REMOTE_REF}/{sha} {sha}"
    )
    lines.append(f"git -C {repo} -c advice.detachedHead=false checkout --quiet --detach {sha}")
