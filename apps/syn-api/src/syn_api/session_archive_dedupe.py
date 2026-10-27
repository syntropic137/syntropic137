"""Store older session revisions as splice references to the newest (#2107).

Run by an operator inside the API container (``just session-archive-dedupe``
gets it there). Dry run is the default: revisions are grouped, every candidate
splice is planned and verified, and the report says what would be saved;
nothing is written. Devops runs the dry run first. ``--apply`` commits each
splice through ``LocalSessionTranscriptArchive.splice_onto``: the same locks
the live workers take, verify before commit, the reference published and
re-verified before the full object is unlinked. Re-running is idempotent and
continues where a stopped run left off.

Revisions are grouped by the envelope's agent and session id, read from each
object's head, and the largest is the base. Grouping is only a guess about
which splices to try: each one is verified byte for byte, so a wrong group
costs a missed saving, never a body. Objects that are not envelopes are left
as they are.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_adapters.session_inventory.local_archive import SpliceStatus
from syn_domain.contexts.agent_sessions import TranscriptIntegrityError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from syn_adapters.session_inventory.local_archive import (
        LocalSessionTranscriptArchive,
        SpliceOutcome,
    )


@dataclass(frozen=True)
class _Revision:
    digest: str
    size: int


@dataclass
class DedupeReport:
    objects: int = 0
    not_envelopes: int = 0
    sessions: int = 0
    """Sessions with more than one full revision."""
    candidates: int = 0
    spliced: int = 0
    already_referenced: int = 0
    not_a_prefix: int = 0
    no_saving: int = 0
    ineligible: int = 0
    retargeted: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    integrity_failures: list[str] = field(default_factory=list[str])
    stopped_by_budget: bool = False

    def record(self, outcome: SpliceOutcome) -> None:
        match outcome.status:
            case SpliceStatus.SPLICED:
                self.spliced += 1
                self.bytes_before += outcome.before
                self.bytes_after += outcome.after
                self.retargeted += outcome.retargeted
            case SpliceStatus.ALREADY_REFERENCED:
                self.already_referenced += 1
            case SpliceStatus.NOT_A_PREFIX:
                self.not_a_prefix += 1
            case SpliceStatus.NO_SAVING:
                self.no_saving += 1
            case SpliceStatus.INELIGIBLE:
                self.ineligible += 1

    def lines(self, *, apply: bool) -> list[str]:
        verb = "spliced" if apply else "would be spliced"
        return [
            f"objects scanned:      {self.objects}",
            f"not envelopes:        {self.not_envelopes}",
            f"multi-revision sessions: {self.sessions}",
            f"older revisions:      {self.candidates}",
            f"{verb + ':':<22}{self.spliced}",
            f"already references:   {self.already_referenced}",
            f"not a prefix:         {self.not_a_prefix}",
            f"no saving:            {self.no_saving}",
            f"ineligible:           {self.ineligible}",
            f"references retargeted: {self.retargeted}",
            f"bytes before:         {self.bytes_before}",
            f"bytes after:          {self.bytes_after}",
            f"bytes saved:          {self.bytes_before - self.bytes_after}",
            f"integrity failures:   {len(self.integrity_failures)}",
            *(f"  {key}" for key in self.integrity_failures),
            *(["stopped at the time budget; re-run to continue"] if self.stopped_by_budget else []),
        ]


def group_revisions(
    archive: LocalSessionTranscriptArchive, report: DedupeReport
) -> list[list[_Revision]]:
    """Each multi-revision session's full objects, largest (the base) first."""
    sessions: dict[tuple[str, str], list[_Revision]] = {}
    for digest in archive.object_keys():
        report.objects += 1
        summary = archive.envelope_summary(digest)
        if summary is None:
            report.not_envelopes += 1
            continue
        key = (summary.agent, summary.session_id)
        sessions.setdefault(key, []).append(_Revision(digest, summary.size))
    groups = [
        sorted(revisions, key=lambda r: (-r.size, r.digest))
        for _, revisions in sorted(sessions.items())
        if len(revisions) > 1
    ]
    report.sessions = len(groups)
    report.candidates = sum(len(group) - 1 for group in groups)
    return groups


def dedupe_archive(
    archive: LocalSessionTranscriptArchive,
    *,
    apply: bool,
    budget_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> DedupeReport:
    report = DedupeReport()
    deadline = clock() + budget_seconds
    for base, *older in group_revisions(archive, report):
        for revision in older:
            if clock() >= deadline:
                report.stopped_by_budget = True
                return report
            try:
                outcome = archive.splice_onto(revision.digest, base.digest, apply=apply)
            except TranscriptIntegrityError:
                report.integrity_failures.append(revision.digest)
                continue
            report.record(outcome)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
    from syn_shared.settings import get_settings

    parser = argparse.ArgumentParser(
        prog="session-archive-dedupe",
        description="Store older session revisions as splice references. Dry run unless --apply.",
    )
    parser.add_argument("--apply", action="store_true", help="write references (default: report)")
    parser.add_argument(
        "--budget-minutes", type=float, default=30.0, help="stop after this long; re-run resumes"
    )
    args = parser.parse_args(argv)
    if args.budget_minutes <= 0:
        parser.error("--budget-minutes must be positive")
    archive = LocalSessionTranscriptArchive(get_settings().session_inventory.archive_dir)
    report = dedupe_archive(archive, apply=args.apply, budget_seconds=args.budget_minutes * 60)
    for line in report.lines(apply=args.apply):
        print(line)
    return 1 if report.integrity_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
