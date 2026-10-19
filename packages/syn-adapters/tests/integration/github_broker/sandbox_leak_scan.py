"""The S2 sandbox leak scan (#1735), as a shell command.

Kept out of the integration module so a unit test can run the same command
against planted files without Docker.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Every GitHub token prefix: installation, classic PAT, OAuth, user-to-server,
# refresh, fine-grained PAT. A capability (``syncap_...``) never matches.
GITHUB_TOKEN_SHAPE = r"\b(gh[pousr]_|github_pat_)[A-Za-z0-9_]+"


def leak_scan(paths: Sequence[str], known_tokens: Sequence[str]) -> str:
    """A command printing each file under ``paths``, and each env line, holding a token.

    A token is one of ``known_tokens`` or anything GitHub-token-shaped, so a
    token the harness never minted is caught too. Prints nothing when clean.
    """
    where = " ".join(shlex.quote(p) for p in paths)
    fixed = " ".join(f"-e {shlex.quote(t)}" for t in known_tokens)
    shape = f"-e {shlex.quote(GITHUB_TOKEN_SHAPE)}"
    return (
        f"grep -rlF {fixed} {where} 2>/dev/null; grep -rlE {shape} {where} 2>/dev/null;"
        f" env | grep -F {fixed}; env | grep -E {shape}"
    )
