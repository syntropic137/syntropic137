"""Operator entry for ``just session-archive-dedupe`` on the VPS (#2107).

The logic is ``syn_api.session_archive_dedupe``, inside the API image, so every
splice goes through the same archive class and locks the live workers use. This
only gets it there, exactly as ``session_archive_compress`` does: ``ssh`` to the
host, ``docker exec`` into the API container, validated flags only. Dry run
unless ``--apply`` is given; run the dry run first and read its report.

    just session-archive-dedupe                       # report what would be saved
    just session-archive-dedupe --apply               # splice; re-run to continue
    just session-archive-dedupe --apply --budget-minutes 60

``SYN_PIT_HOST`` names the host (default as ``scripts/pit_stop.sh``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from infra.scripts.session_archive_compress import command as _command
from infra.scripts.session_archive_compress import main as _main

if TYPE_CHECKING:
    from collections.abc import Sequence

MODULE = "syn_api.session_archive_dedupe"


def command(host: str, flags: Sequence[str]) -> list[str]:
    return _command(host, flags, MODULE)


def main(argv: Sequence[str] | None = None) -> int:
    return _main(argv, module=MODULE, name="session-archive-dedupe", usage=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
