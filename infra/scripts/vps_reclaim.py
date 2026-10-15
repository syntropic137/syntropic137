"""Operator entry for ``just vps-reclaim``: run the backlog reclaim as root on the VPS (#1983).

The logic is ``syn_api.vps_reclaim``, inside the API image, so it runs with
exactly the predicate the automatic reclaimer uses and its tests pin. This
script only gets it there: ``ssh`` to the host, ``docker exec -u 0`` into the
API container (root, so trees a workspace wrote as root can be deleted; the
container already has the workspace bind, docker and the database), and pass
through the operator's flags. Dry run unless ``--apply`` is given.

    just vps-reclaim                     # dry run: what would go, and why the rest stays
    just vps-reclaim --apply             # sets maintenance, enforces quiescence, deletes
    just vps-reclaim --apply --budget-minutes 20
    just vps-reclaim --apply --lift-maintenance

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
MODULE = "syn_api.vps_reclaim"

_FLAGS = {"--apply", "--lift-maintenance"}
_VALUED = {"--budget-minutes"}


class UsageError(ValueError):
    """Flags this tool does not pass through."""


def validated(flags: Sequence[str]) -> list[str]:
    """The flags, unchanged, or `UsageError`: nothing else reaches a root shell."""
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
    if "--lift-maintenance" in out and "--apply" not in out:
        raise UsageError("--lift-maintenance only makes sense with --apply")
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
        "-u",
        "0",
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
        print(f"vps-reclaim: {exc}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    return subprocess.run(argv_out, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
