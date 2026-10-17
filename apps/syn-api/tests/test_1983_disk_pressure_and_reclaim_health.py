"""#1983: low disk wakes the reclaimer with or without a webhook, and /health
shows every directory the reclaimer is holding and why.

The monitor runs over the real `DiskSpaceGuard`; only the filesystem
measurement and the webhook are doubles.
"""

from __future__ import annotations

import asyncio

import pytest

from syn_adapters.workspace_backends.remote_refs import (
    GitLsRemote,
    RemoteRefsError,
    github_slug,
    parse_ls_remote,
)
from syn_api.services import disk_pressure
from syn_api.services.degraded_reasons import DegradedReason
from syn_api.services.disk_pager import DiskPage, DiskPager
from syn_api.services.disk_pressure import DiskPressureMonitor
from syn_api.services.workspace_dir_reclaim import ReclaimPass, RetainedDir
from syn_api.services.workspace_reclaim_status import ReclaimStatus
from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskThresholds, DiskUsage
from syn_domain.contexts.orchestration import RetainedReason

pytestmark = pytest.mark.unit


class _Disk:
    path = "/workspaces"

    def __init__(self) -> None:
        self.free_percent = 50.0

    def usage(self) -> DiskUsage:
        return DiskUsage(free_bytes=int(self.free_percent * 10), total_bytes=1000)


def _guard(disk: _Disk) -> DiskSpaceGuard:
    return DiskSpaceGuard(
        disk,
        DiskThresholds(
            refuse_admission_below_bytes=0,
            degraded_below_bytes=0,
            refuse_basis="test",
            refuse_admission_below_percent=5.0,
            degraded_below_percent=15.0,
        ),
    )


# --- the monitor runs and wakes without a webhook ---


async def test_entering_low_wakes_the_reclaimer_with_no_pager_at_all() -> None:
    disk = _Disk()
    wake = asyncio.Event()
    monitor = DiskPressureMonitor(check=_guard(disk).check, wake=wake)
    assert monitor.pager is None
    assert await monitor.run_once() == "ok"
    assert not wake.is_set()
    disk.free_percent = 10.0
    assert await monitor.run_once() == "low"
    assert wake.is_set()


async def test_staying_low_does_not_wake_again_and_critical_after_low_does_not_either() -> None:
    disk = _Disk()
    wake = asyncio.Event()
    monitor = DiskPressureMonitor(check=_guard(disk).check, wake=wake)
    disk.free_percent = 10.0
    await monitor.run_once()
    wake.clear()
    await monitor.run_once()
    disk.free_percent = 3.0
    assert await monitor.run_once() == "critical"
    assert not wake.is_set()
    disk.free_percent = 50.0
    await monitor.run_once()
    disk.free_percent = 3.0
    await monitor.run_once()
    assert wake.is_set()  # a fresh entry after recovery wakes it again


async def test_the_pager_rides_along_on_the_same_verdict() -> None:
    disk = _Disk()
    sent: list[DiskPage] = []

    async def send(page: DiskPage) -> None:
        sent.append(page)

    wake = asyncio.Event()
    monitor = DiskPressureMonitor(check=_guard(disk).check, wake=wake)
    monitor.pager = DiskPager(check=lambda: monitor.latest or _guard(disk).check(), send=send)
    disk.free_percent = 10.0
    await monitor.run_once()
    assert [p.state for p in sent] == ["low"]
    assert wake.is_set()


async def test_an_unreadable_disk_neither_raises_nor_wakes() -> None:
    def broken() -> object:
        raise OSError("statvfs failed")

    wake = asyncio.Event()
    monitor = DiskPressureMonitor(check=broken, wake=wake)  # type: ignore[arg-type]
    assert await monitor.run_once() is None
    assert not wake.is_set()


async def test_the_monitor_starts_with_no_webhook_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring: no SYN_DISK_PAGE_WEBHOOK_URL still starts the monitor, pager-less."""
    from syn_shared.settings import get_settings

    disk = _Disk()
    disk.free_percent = 10.0
    monkeypatch.setattr("syn_api._wiring_admission.get_disk_space_guard", lambda: _guard(disk))
    monkeypatch.setattr(get_settings().disk, "page_webhook_url", "")
    monkeypatch.setattr(disk_pressure, "_pressure", None)
    try:
        disk_pressure.start_disk_pressure_monitor()
        task = disk_pressure._monitor_task
        assert task is not None
        await asyncio.wait_for(disk_pressure.pressure_event().wait(), timeout=2)
    finally:
        await disk_pressure.stop_disk_pressure_monitor()
        monkeypatch.setattr(disk_pressure, "_pressure", None)


def test_the_production_reclaimer_wires_without_a_webhook() -> None:
    """The real factory constructs: deletion of wiring breaks here, not on the VPS."""
    from syn_adapters.workspace_backends.remote_refs import GitLsRemote as Remote
    from syn_api.services.workspace_dir_reclaim import default_reclaimer

    reclaimer = default_reclaimer(lambda: True)
    assert isinstance(reclaimer.remotes, Remote)
    assert reclaimer.settle_seconds == 600.0
    assert reclaimer.dry_run is False


# --- /health: every retain reason, and the degrade ---


def _pass(*kept: tuple[RetainedReason, int], reclaimed_bytes: int = 0) -> ReclaimPass:
    return ReclaimPass(
        reclaimed=("ws-gone",) if reclaimed_bytes else (),
        reclaimed_bytes=reclaimed_bytes,
        retained=tuple(
            RetainedDir(f"ws-{i}", reason, "detail", size) for i, (reason, size) in enumerate(kept)
        ),
    )


def test_every_retained_reason_is_counted_with_its_bytes() -> None:
    status = ReclaimStatus()
    kept = [(reason, 10 * (i + 1)) for i, reason in enumerate(RetainedReason)]
    status.record(_pass(*kept, *kept), at=1000.0)
    snapshot = status.snapshot(1000.0)
    assert {t.reason for t in snapshot.retained} == set(RetainedReason)
    for tally in snapshot.retained:
        size = dict(kept)[tally.reason]
        assert (tally.count, tally.size_bytes) == (2, 2 * size)


def test_reclaimed_bytes_are_summed_over_a_day_only() -> None:
    status = ReclaimStatus()
    status.record(_pass(reclaimed_bytes=100), at=0.0)
    status.record(_pass(reclaimed_bytes=50), at=3600.0)
    assert status.snapshot(3600.0).reclaimed_bytes_24h == 150
    assert status.snapshot(24 * 3600.0 + 1).reclaimed_bytes_24h == 50


def test_a_delete_failing_two_passes_running_degrades_and_a_clean_pass_clears_it() -> None:
    status = ReclaimStatus()
    failed = _pass((RetainedReason.DELETE_FAILED, 1))
    status.record(failed, at=1.0)
    assert not status.snapshot(1.0).degraded
    status.record(ReclaimPass(paused="maintenance"), at=2.0)  # a paused pass decides nothing
    status.record(failed, at=3.0)
    assert status.snapshot(3.0).degraded
    status.record(_pass(), at=4.0)
    assert not status.snapshot(4.0).degraded


def test_health_reports_the_reclaimer_and_degrades_on_stuck_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.services import health_probes, workspace_reclaim_status

    disk = _Disk()
    status = ReclaimStatus()
    status.record(_pass((RetainedReason.DIRTY, 7), (RetainedReason.DELETE_FAILED, 3)), at=1.0)
    status.record(_pass((RetainedReason.DELETE_FAILED, 3)), at=2.0)
    monkeypatch.setattr(workspace_reclaim_status, "_status", status)
    monkeypatch.setattr("syn_api._wiring_admission.get_disk_space_guard", lambda: _guard(disk))
    health, reasons = health_probes.describe_disk_health()
    assert health is not None and health.reclaim is not None
    assert [(r.reason, r.count, r.size_bytes) for r in health.reclaim.retained] == [
        (RetainedReason.DELETE_FAILED, 1, 3)
    ]
    assert health.reclaim.delete_failed_passes == 2
    assert DegradedReason.WORKSPACE_RECLAIM in reasons
    assert health.reclaim.last_pass_at is not None


def test_health_reports_a_paused_reclaimer() -> None:
    status = ReclaimStatus()
    status.record(ReclaimPass(paused="maintenance"), at=5.0)
    assert status.snapshot(5.0).paused == "maintenance"


# --- the remote read ---


def test_ls_remote_output_is_parsed_and_a_malformed_line_refused() -> None:
    sha1 = "a" * 40
    sha256 = "b" * 64
    out = f"{sha1}\tHEAD\n{sha1}\trefs/heads/main\n{sha256}\trefs/tags/v1^{{}}\n"
    assert parse_ls_remote(out) == frozenset({sha1, sha256})
    with pytest.raises(RemoteRefsError):
        parse_ls_remote("not an oid\trefs/heads/main\n")


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://github.com/syntropic137/syntropic137", "syntropic137/syntropic137"),
        ("https://github.com/o/r.git", "o/r"),
        ("http://github.com/o/r", None),
        ("https://gitlab.com/o/r", None),
        ("/srv/remote.git", None),
        ("https://github.com/o", None),
    ],
)
def test_only_https_github_urls_get_an_app_token(url: str, slug: str | None) -> None:
    assert github_slug(url) == slug


async def test_a_remote_that_looks_like_an_option_is_refused() -> None:
    with pytest.raises(RemoteRefsError):
        await GitLsRemote().advertised("--upload-pack=touch /tmp/pwned")
