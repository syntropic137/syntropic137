"""Operator entry for ``just session-archive-compress`` on the VPS (#2107).

The logic is ``syn_api.session_archive_compress``, inside the API image, so it
re-encodes objects through the same archive class and locks the live workers
use. This script only gets it there: ``ssh`` to the host and ``docker exec``
into the API container as its own user (the archive volume belongs to it), and
pass through the operator's flags. Dry run unless ``--apply`` is given.

    just session-archive-compress                       # report what would be saved
    just session-archive-compress --apply               # rewrite; re-run to continue
    just session-archive-compress --apply --budget-minutes 60

``SYN_PIT_HOST`` names the host (default as ``scripts/pit_stop.sh``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_HOST = "root@100.114.86.77"
API_CONTAINER = "syn137-api"
MODULE = "syn_api.session_archive_compress"

_FLAGS = {"--apply"}
_VALUED = {"--budget-minutes"}


class UsageError(ValueError):
    """Flags this tool does not pass through."""


def validated(flags: Sequence[str]) -> list[str]:
    """The flags, unchanged, or `UsageError`: nothing else reaches the host shell."""
    out: list[str] = []
    pending: str | None = None
    for flag in flags:
        if pending is not None:
            try:
                if float(flag) <= 0:
                    raise ValueError
            except ValueError:
                raise UsageError(f"{pending} needs a positive number, not {flag!r}") from None
            out += [pending, flag]
            pending = None
        elif flag in _VALUED:
            pending = flag
        elif flag in _FLAGS:
            out.append(flag)
        else:
            raise UsageError(f"unknown flag {flag!r}")
    if pending is not None:
        raise UsageError(f"{pending} needs a value")
    return out


def command(host: str, flags: Sequence[str]) -> list[str]:
    """The argv run locally. Every flag is validated, so none can inject a shell word."""
    return [
        "ssh",
        "-o",
        "ServerAliveInterval=20",
        host,
        "docker",
        "exec",
        API_CONTAINER,
        "python",
        "-m",
        MODULE,
        *validated(flags),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        argv_out = command(os.environ.get("SYN_PIT_HOST", DEFAULT_HOST), args)
    except UsageError as exc:
        print(f"session-archive-compress: {exc}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    return subprocess.run(argv_out, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
