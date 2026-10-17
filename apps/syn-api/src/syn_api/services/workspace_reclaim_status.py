"""What the workspace reclaimer last did, for /health (#1983).

Before this, a kept directory was a log line, and nobody looked until the
disk was at 99%. Now every pass is recorded here and /health shows when it
ran, whether it was paused or skipped, what it freed in the last day, and how
many directories (and bytes) it is holding for each `RetainedReason`.

ACKNOWLEDGED in-memory state (ADR-060): this is Lane 2 telemetry about this
process's own passes, not domain state and not a dedup key. A restart loses
it, and the next pass (at most one interval later) fills it again; nothing
decides anything from it but /health's degraded flag, which a restart can
only clear, never raise.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import RetainedReason

if TYPE_CHECKING:
    from syn_api.services.workspace_dir_reclaim import ReclaimPass

#: Window for ``reclaimed_bytes_24h``.
_DAY_SECONDS = 24 * 3600.0

#: Consecutive passes with a failed delete before /health degrades.
DELETE_FAILED_PASSES_TO_DEGRADE = 2


@dataclass(frozen=True)
class RetainedTally:
    reason: RetainedReason
    count: int
    size_bytes: int


@dataclass(frozen=True)
class ReclaimSnapshot:
    """The reclaimer's state at one moment, ready for /health."""

    last_pass_at: float | None
    paused: str | None
    skipped: str | None
    reclaimed_bytes_24h: int
    dry_run_reclaimable: int
    deletes_in_progress: int
    out_of_time: bool
    retained: tuple[RetainedTally, ...]
    delete_failed_passes: int

    @property
    def degraded(self) -> bool:
        return self.delete_failed_passes >= DELETE_FAILED_PASSES_TO_DEGRADE


@dataclass
class ReclaimStatus:
    """The last pass, and a day of reclaimed bytes. One per process."""

    last_pass_at: float | None = None
    last: ReclaimPass | None = None
    delete_failed_passes: int = 0
    _reclaimed: deque[tuple[float, int]] = field(default_factory=deque)

    def record(self, result: ReclaimPass, *, at: float) -> None:
        self.last_pass_at = at
        self.last = result
        if result.reclaimed_bytes:
            self._reclaimed.append((at, result.reclaimed_bytes))
        if result.skipped is None and result.paused is None:
            failed = any(r.reason is RetainedReason.DELETE_FAILED for r in result.retained)
            self.delete_failed_passes = self.delete_failed_passes + 1 if failed else 0
        self._forget_before(at - _DAY_SECONDS)

    def snapshot(self, now: float) -> ReclaimSnapshot:
        self._forget_before(now - _DAY_SECONDS)
        tallies: dict[RetainedReason, tuple[int, int]] = {}
        last = self.last
        for kept in last.retained if last is not None else ():
            count, size = tallies.get(kept.reason, (0, 0))
            tallies[kept.reason] = (count + 1, size + kept.size_bytes)
        return ReclaimSnapshot(
            last_pass_at=self.last_pass_at,
            paused=None if last is None else last.paused,
            skipped=None if last is None else last.skipped,
            reclaimed_bytes_24h=sum(size for _, size in self._reclaimed),
            dry_run_reclaimable=0 if last is None else len(last.would_reclaim),
            deletes_in_progress=0 if last is None else len(last.deleting),
            out_of_time=False if last is None else last.out_of_time,
            retained=tuple(
                RetainedTally(reason, count, size)
                for reason, (count, size) in sorted(tallies.items())
            ),
            delete_failed_passes=self.delete_failed_passes,
        )

    def _forget_before(self, cutoff: float) -> None:
        while self._reclaimed and self._reclaimed[0][0] < cutoff:
            self._reclaimed.popleft()


_status = ReclaimStatus()


def reclaim_status() -> ReclaimStatus:
    """This process's reclaimer status."""
    return _status
