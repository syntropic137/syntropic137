"""Per-instance probes that /health reports and that need no lifecycle state.

Kept apart from ``lifecycle`` so ``health_check`` there only assembles the
response; each probe here answers one question and never raises.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_api.services.degraded_reasons import DegradedReason
from syn_api.services.workspace_reclaim_status import DELETE_FAILED_PASSES_TO_DEGRADE
from syn_api.types import (
    DiskSpaceHealth,
    RetainedWorkspaceDirs,
    SessionExpiryHoldCount,
    SessionExpiryHoldsHealth,
    SessionStoreHealth,
    WorkspaceReclaimHealth,
    format_bytes,
)

if TYPE_CHECKING:
    from pathlib import Path

    from syn_shared.codex_auth_status import CodexAuthStatus

logger = logging.getLogger(__name__)


def describe_disk_health() -> tuple[DiskSpaceHealth | None, list[DegradedReason]]:
    """Free space on the workspace volume, judged by the admission gate's own guard.

    The SAME guard admission refuses with, so a refused execution is always
    explained by a ``critical`` block here. Never raises: a probe that could
    take /health down is worse than an omitted block.
    """
    try:
        from syn_api._wiring_admission import get_disk_space_guard

        check = get_disk_space_guard().check()
    except Exception:
        logger.warning("disk space probe could not be built", exc_info=True)
        return None, []
    reclaim = describe_workspace_reclaim()
    health = DiskSpaceHealth(
        path=check.path,
        state=check.state.value,
        free_percent=None if check.usage is None else round(check.usage.free_percent, 2),
        free_bytes=None if check.usage is None else check.usage.free_bytes,
        degraded_below_bytes=check.thresholds.degraded_below_bytes,
        refuse_admission_below_bytes=check.thresholds.refuse_admission_below_bytes,
        degraded_below_percent=check.thresholds.degraded_below_percent,
        refuse_admission_below_percent=check.thresholds.refuse_admission_below_percent,
        detail=check.detail,
        reclaim=reclaim,
    )
    reasons = [DegradedReason.DISK_SPACE] if check.is_degraded else []
    if reclaim is not None and reclaim.delete_failed_passes >= DELETE_FAILED_PASSES_TO_DEGRADE:
        reasons.append(DegradedReason.WORKSPACE_RECLAIM)
    return health, reasons


def describe_workspace_reclaim() -> WorkspaceReclaimHealth | None:
    """The reclaimer's last pass, per retained reason (#1983). Never raises."""
    try:
        from syn_api.services.workspace_reclaim_status import reclaim_status

        snapshot = reclaim_status().snapshot(time.time())
        return WorkspaceReclaimHealth(
            last_pass_at=(
                None
                if snapshot.last_pass_at is None
                else datetime.fromtimestamp(snapshot.last_pass_at, tz=UTC)
            ),
            paused=snapshot.paused,
            last_pass_skipped=snapshot.skipped,
            reclaimed_bytes_24h=snapshot.reclaimed_bytes_24h,
            dry_run_reclaimable=snapshot.dry_run_reclaimable,
            deletes_in_progress=snapshot.deletes_in_progress,
            out_of_time=snapshot.out_of_time,
            retained=[
                RetainedWorkspaceDirs(reason=t.reason, count=t.count, size_bytes=t.size_bytes)
                for t in snapshot.retained
            ],
            delete_failed_passes=snapshot.delete_failed_passes,
        )
    except Exception:
        logger.warning("workspace reclaim probe failed", exc_info=True)
        return None


def describe_codex_auth_health() -> CodexAuthStatus | None:
    """How fresh this instance's codex credential is, or None if it cannot be said.

    WHY HERE: a stale codex credential is invisible until a phase fails, and the
    failure names no credential. Every instance holds its own copy and expires
    independently, so this has to be reported per instance rather than centrally,
    which is exactly what a health endpoint is for.

    Never raises. A freshness hint that can take /health down is worse than no
    hint, so any failure degrades to omitting the block.
    """
    try:
        from syn_shared.codex_auth_status import describe_codex_auth
        from syn_shared.codex_credentials import resolve_configured_codex_credential

        # The same precedence a codex phase gets (#1971): CODEX_AUTH_JSON, then
        # OPENAI_API_KEY. Only a state and a detail leave this function.
        resolved = resolve_configured_codex_credential()
        if resolved is None:
            return describe_codex_auth(None)
        return describe_codex_auth(resolved.auth_json, source=resolved.source)
    except Exception:
        logger.debug("codex auth freshness probe failed", exc_info=True)
        return None


SESSION_STORE_CACHE_SECONDS = 300.0
"""The archive walk is O(objects); /health is polled far more often than this."""


@dataclass
class _SessionStoreCache:
    """The last measurement and the one walk refreshing it. A cache, never state."""

    refreshed_at: float | None = None
    """``time.monotonic()`` when ``value`` was published; ``None`` before the first."""
    value: SessionStoreHealth | None = None
    refresh: asyncio.Task[None] | None = None


_session_store_cache = _SessionStoreCache()


async def describe_session_store() -> SessionStoreHealth | None:
    """Session archive size and growth (#2107) as last measured. Never raises, never waits.

    A stale or missing value starts one background walk and is returned as is:
    /health answers within its probe timeout however slow the disk, a
    cancelled request cannot strand the walk, and a walk slower than the
    window never overlaps another.
    """
    cache = _session_store_cache
    stale = (
        cache.refreshed_at is None
        or time.monotonic() - cache.refreshed_at >= SESSION_STORE_CACHE_SECONDS
    )
    if stale and (cache.refresh is None or cache.refresh.done()):
        cache.refresh = asyncio.create_task(_refresh_session_store(cache))
    return cache.value


async def _refresh_session_store(cache: _SessionStoreCache) -> None:
    try:
        from syn_shared.settings import get_settings

        root = get_settings().session_inventory.archive_dir
        value = await asyncio.to_thread(_measure_session_store, root, time.time())
    except Exception:
        logger.warning("session store probe failed", exc_info=True)
        value = None
    if value is not None:
        holds = await _describe_expiry_holds()
        if holds is not None:
            value = value.model_copy(update={"expiry_holds": holds})
    cache.value = value
    cache.refreshed_at = time.monotonic()


async def _describe_expiry_holds() -> SessionExpiryHoldsHealth | None:
    """Bodies the confirmed-expiry gate keeps, by reason; None when the gate is off."""
    try:
        from syn_api._wiring_inventory import get_inventory_runtime

        source = get_inventory_runtime().expiry_holds
        if source is None:
            return None
        counts = await source.summary()
    except Exception:
        logger.warning("session expiry holds probe failed", exc_info=True)
        return None
    return expiry_holds_health(
        [SessionExpiryHoldCount(hold=c.hold.value, bodies=c.bodies, bytes=c.bytes) for c in counts]
    )


def expiry_holds_health(counts: list[SessionExpiryHoldCount]) -> SessionExpiryHoldsHealth:
    bodies = sum(count.bodies for count in counts)
    total = sum(count.bytes for count in counts)
    reasons = ", ".join(
        f"{count.hold} {count.bodies} ({format_bytes(count.bytes)})" for count in counts
    )
    detail = (
        f"expiry gate keeps {bodies} bodies ({format_bytes(total)}): {reasons}"
        if counts
        else "expiry gate keeps nothing"
    )
    return SessionExpiryHoldsHealth(
        held_bodies=bodies, held_bytes=total, by_hold=counts, detail=detail
    )


def _measure_session_store(root: Path, now: float) -> SessionStoreHealth | None:
    from syn_adapters.session_inventory.archive_usage import measure_archive_usage

    usage = measure_archive_usage(root, now)
    if usage is None:
        return None
    per_day = usage.added_bytes_7d // 7
    runway = None if per_day == 0 else round(usage.filesystem_free_bytes / per_day, 1)
    detail = (
        f"{format_bytes(usage.stored_bytes)} in {usage.object_count} objects and "
        f"{usage.reference_count} references; +{format_bytes(usage.added_bytes_24h)} in 24h, "
        f"+{format_bytes(per_day)}/day over 7d; "
        f"{format_bytes(usage.filesystem_free_bytes)} free"
        + ("" if runway is None else f", about {runway:.0f} days at that rate")
    )
    return SessionStoreHealth(
        path=str(root),
        measured_at=datetime.fromtimestamp(now, tz=UTC),
        stored_bytes=usage.stored_bytes,
        object_count=usage.object_count,
        reference_count=usage.reference_count,
        added_bytes_24h=usage.added_bytes_24h,
        added_bytes_per_day_7d=per_day,
        filesystem_free_bytes=usage.filesystem_free_bytes,
        days_until_full=runway,
        detail=detail,
    )
