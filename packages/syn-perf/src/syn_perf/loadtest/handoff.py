"""How one stub phase hands the branch head to the next (plan 6.1, #1310).

Every implement-v3 phase after premise names the full commit SHA it worked on,
and the phase after it refuses to continue unless the branch is still at that
SHA (``phases/verify.md``, ``fix.md``, ``reverify.md``, ``finalize_pr.md``).
A stub that names only the branch would skip the check that catches a branch
pushed over mid-run, so the head travels in one fixed line that is written and
read from the same definition.
"""

import re
from typing import Final

HEAD_SHA_LINE: Final = "Head SHA: `{head_sha}`"
"""The line an artifact template carries to name the head. Filled per phase."""

FULL_SHA: Final = re.compile(r"[0-9a-f]{40}")

_HEAD_SHA_IN_ARTIFACT: Final = re.compile(
    "^" + re.escape(HEAD_SHA_LINE).replace(re.escape("{head_sha}"), f"({FULL_SHA.pattern})") + "$",
    re.MULTILINE,
)


def head_sha_handed_over(artifact: str, *, branch_head: str) -> str:
    """The full SHA a previous phase's artifact names, checked against the branch.

    ``branch_head`` is where the branch is now (``git rev-parse
    origin/<branch>`` with a tree, ``git ls-remote`` without one). An artifact
    that names no full SHA, names more than one, or names a different one is
    refused, exactly as the real phase stops rather than work on a head
    nobody reviewed.
    """
    named = _HEAD_SHA_IN_ARTIFACT.findall(artifact)
    if len(named) != 1:
        msg = f"the previous artifact must name exactly one full head SHA; it names {named}"
        raise ValueError(msg)
    if named[0] != branch_head:
        msg = f"the previous phase handed over {named[0]} but the branch is at {branch_head}"
        raise ValueError(msg)
    return branch_head
