"""Re-encode existing session archive objects gzip-compressed (#2107).

Run once by an operator inside the API container (``just
session-archive-compress`` gets it there). Dry run is the default: every object
is read, verified and encoded, and the report says what would be saved; nothing
is rewritten. ``--apply`` rewrites each object through
``LocalSessionTranscriptArchive.compress_in_place``: the same per-object lock
the live workers take, a two-layer verify, then an atomic replace. It is safe
beside running workers and resumable: an already compressed object is skipped,
so re-running continues where a stopped run left off.

Nothing is deleted. An object that fails verification is reported and left as
it is.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_adapters.session_inventory.local_archive import CompressionStatus
from syn_domain.contexts.agent_sessions import TranscriptIntegrityError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive


@dataclass
class CompressionReport:
    objects: int = 0
    already_compressed: int = 0
    rewritten: int = 0
    incompressible: int = 0
    absent: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    integrity_failures: list[str] = field(default_factory=list)
    stopped_by_budget: bool = False

    def lines(self, *, apply: bool) -> list[str]:
        verb = "rewritten" if apply else "would be rewritten"
        saved = self.bytes_before - self.bytes_after
        return [
            f"objects scanned:      {self.objects}",
            f"already compressed:   {self.already_compressed}",
            f"{verb + ':':<22}{self.rewritten}",
            f"incompressible:       {self.incompressible}",
            f"absent or deleted:    {self.absent}",
            f"bytes before:         {self.bytes_before}",
            f"bytes after:          {self.bytes_after}",
            f"bytes saved:          {saved}",
            f"integrity failures:   {len(self.integrity_failures)}",
            *(f"  {key}" for key in self.integrity_failures),
            *(["stopped at the time budget; re-run to continue"] if self.stopped_by_budget else []),
        ]


def compress_archive(
    archive: LocalSessionTranscriptArchive,
    *,
    apply: bool,
    budget_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> CompressionReport:
    report = CompressionReport()
    deadline = clock() + budget_seconds
    for key in archive.object_keys():
        if clock() >= deadline:
            report.stopped_by_budget = True
            break
        report.objects += 1
        try:
            outcome = archive.compress_in_place(key, apply=apply)
        except TranscriptIntegrityError:
            report.integrity_failures.append(key)
            continue
        if outcome is None:
            report.absent += 1
            continue
        report.bytes_before += outcome.before
        report.bytes_after += outcome.after
        if outcome.status is CompressionStatus.ALREADY_COMPRESSED:
            report.already_compressed += 1
        elif outcome.status is CompressionStatus.INCOMPRESSIBLE:
            report.incompressible += 1
        else:
            report.rewritten += 1
    return report


def main(argv: Sequence[str] | None = None) -> int:
    from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
    from syn_shared.settings import get_settings

    parser = argparse.ArgumentParser(
        prog="session-archive-compress",
        description="Re-encode session archive objects gzip-compressed. Dry run unless --apply.",
    )
    parser.add_argument("--apply", action="store_true", help="rewrite objects (default: report)")
    parser.add_argument(
        "--budget-minutes", type=float, default=30.0, help="stop after this long; re-run resumes"
    )
    args = parser.parse_args(argv)
    if args.budget_minutes <= 0:
        parser.error("--budget-minutes must be positive")
    archive = LocalSessionTranscriptArchive(get_settings().session_inventory.archive_dir)
    report = compress_archive(archive, apply=args.apply, budget_seconds=args.budget_minutes * 60)
    for line in report.lines(apply=args.apply):
        print(line)
    return 1 if report.integrity_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
