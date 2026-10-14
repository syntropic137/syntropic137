"""A nearly-full workspace volume refuses admission instead of failing mid-write (#1560, #1947).

Measured through a fake port: no test here touches a real filesystem.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts._shared.disk_space import (
    DiskCheck,
    DiskSpaceGuard,
    DiskState,
    DiskThresholds,
    DiskUsage,
    InsufficientDiskSpaceError,
)
from syn_domain.contexts._shared.maintenance import AdmissionGate, MaintenanceMode

pytestmark = pytest.mark.unit

_GIB = 2**30


class _FakeDisk:
    """`DiskSpacePort` double: reports a fixed free percentage, or cannot look."""

    def __init__(self, free_percent: float | None) -> None:
        self._free_percent = free_percent

    @property
    def path(self) -> str:
        return "/workspaces"

    def usage(self) -> DiskUsage:
        if self._free_percent is None:
            raise FileNotFoundError("/workspaces")
        total = 100 * _GIB
        return DiskUsage(free_bytes=int(total * self._free_percent / 100), total_bytes=total)


class _Port:
    def __init__(self) -> None:
        self.reads = 0

    async def current(self) -> MaintenanceMode:
        self.reads += 1
        return MaintenanceMode()

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        return MaintenanceMode(active=active, reason=reason, actor=actor)


class _SizedDisk:
    """`DiskSpacePort` double: a disk of a given size with a given amount free."""

    def __init__(self, *, free_gib: float, total_gib: float) -> None:
        self._usage = DiskUsage(free_bytes=int(free_gib * _GIB), total_bytes=int(total_gib * _GIB))

    @property
    def path(self) -> str:
        return "/workspaces"

    def usage(self) -> DiskUsage:
        return self._usage


#: The defaults at SYN_EXECUTION_MAX_CONCURRENT=4: 3 GiB per run x 4 = 12 GiB
#: refuses, twice that degrades.
_DEFAULTS = DiskThresholds.from_gib(
    refuse_admission_below_gib=12.0,
    degraded_below_gib=24.0,
    refuse_basis="SYN_DISK_RUN_RESERVE_GIB=3 per run x SYN_EXECUTION_MAX_CONCURRENT=4",
)

#: Percent floors only, as an operator who set the pre-#1947 env vars gets
#: them: GiB floors at zero so only the percent can trip.
_PERCENT_ONLY = DiskThresholds(
    refuse_admission_below_bytes=0,
    degraded_below_bytes=0,
    refuse_basis="test",
    refuse_admission_below_percent=5.0,
    degraded_below_percent=10.0,
)


def _guard(free_percent: float | None) -> DiskSpaceGuard:
    return DiskSpaceGuard(_FakeDisk(free_percent), _PERCENT_ONLY)


def _sized(free_gib: float, total_gib: float, thresholds: DiskThresholds = _DEFAULTS) -> DiskCheck:
    return DiskSpaceGuard(_SizedDisk(free_gib=free_gib, total_gib=total_gib), thresholds).check()


@pytest.mark.parametrize(
    ("free_percent", "state"),
    [
        (50.0, DiskState.OK),
        (10.0, DiskState.OK),
        (9.9, DiskState.LOW),
        (5.0, DiskState.LOW),
        (4.9, DiskState.CRITICAL),
        (None, DiskState.UNMEASURABLE),
    ],
)
def test_the_guard_judges_free_space_against_both_thresholds(
    free_percent: float | None, state: DiskState
) -> None:
    assert _guard(free_percent).check().state is state


async def test_admission_below_the_floor_is_refused_before_anything_is_admitted() -> None:
    port = _Port()
    gate = AdmissionGate(port, disk=_guard(3.0))

    with pytest.raises(InsufficientDiskSpaceError) as refused:
        async with gate.admitting():
            pytest.fail("the body ran on a full disk")

    assert "(3.0% of 100 GiB)" in str(refused.value)
    assert refused.value.check.state is DiskState.CRITICAL
    # Refused before the durable read, and no lease is left outstanding: a
    # deploy closing the gate now must not wait on an admission that never was.
    assert port.reads == 0
    closed = await gate.set_mode(active=True, reason="deploy", actor="test")
    assert closed.active


async def test_refuse_early_also_refuses_below_the_floor() -> None:
    gate = AdmissionGate(_Port(), disk=_guard(1.0))

    with pytest.raises(InsufficientDiskSpaceError):
        await gate.refuse_early()


@pytest.mark.parametrize("free_percent", [7.0, None])
async def test_low_or_unmeasurable_disk_still_admits(free_percent: float | None) -> None:
    """Degraded is a warning, and "could not look" is not a fact to refuse on."""
    gate = AdmissionGate(_Port(), disk=_guard(free_percent))

    await gate.refuse_early()
    async with gate.admitting() as ticket:
        ticket.abort()


def test_a_large_disk_with_a_low_percent_but_plenty_of_gib_admits() -> None:
    """#1947: 71 GiB free of a 2 TB disk is 3.9%, and far more than any run needs."""
    check = _sized(71, 1858)

    assert check.usage is not None and check.usage.free_percent < 5
    assert check.state is DiskState.OK
    assert not check.refuses_admission


def test_a_small_disk_below_the_gib_floor_refuses_whatever_its_percent() -> None:
    """6% of a 100 GiB disk is 6 GiB: room for two runs, not four."""
    check = _sized(6, 100)

    assert check.state is DiskState.CRITICAL
    with pytest.raises(InsufficientDiskSpaceError) as refused:
        DiskSpaceGuard(_SizedDisk(free_gib=6, total_gib=100), _DEFAULTS).refuse_if_full()
    message = str(refused.value)
    # It says how much is free, what the floor is and where it came from, and
    # exactly what to do: free space, or move the floor in the self-host env.
    assert "6 GiB free on /workspaces (6.0% of 100 GiB)" in message
    assert "new executions refused below 12 GiB" in message
    assert "SYN_DISK_RUN_RESERVE_GIB=3 per run x SYN_EXECUTION_MAX_CONCURRENT=4" in message
    assert "delete finished workspace directories" in message
    assert "docker image prune" in message
    assert "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB" in message
    assert "~/.syntropic137/.env" in message


@pytest.mark.parametrize(
    ("free_gib", "state"),
    [
        (500.0, DiskState.OK),
        (24.0, DiskState.OK),  # exactly the degraded floor: not below it
        (23.9, DiskState.LOW),
        (12.0, DiskState.LOW),  # exactly the admission floor: still admitted
        (11.9, DiskState.CRITICAL),
        (0.0, DiskState.CRITICAL),
    ],
)
def test_gib_floors_and_their_boundaries(free_gib: float, state: DiskState) -> None:
    assert _sized(free_gib, 2000).state is state


def test_the_degraded_band_warns_but_still_admits() -> None:
    check = _sized(20, 2000)

    assert check.state is DiskState.LOW
    assert check.is_degraded
    assert not check.refuses_admission


def test_one_byte_under_the_floor_refuses() -> None:
    floor = _DEFAULTS.refuse_admission_below_bytes
    at = DiskUsage(free_bytes=floor, total_bytes=100 * floor)
    under = DiskUsage(free_bytes=floor - 1, total_bytes=100 * floor)

    assert not _DEFAULTS.refuses(at)
    assert _DEFAULTS.refuses(under)


def test_a_configured_percent_floor_still_refuses_on_its_own() -> None:
    """Back-compat: SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT keeps working, and
    crossing either floor is enough."""
    both = DiskThresholds.from_gib(
        refuse_admission_below_gib=12.0,
        degraded_below_gib=24.0,
        refuse_basis="test",
        refuse_admission_below_percent=5.0,
        degraded_below_percent=15.0,
    )

    check = _sized(71, 1858, both)

    assert check.state is DiskState.CRITICAL
    assert "or 5%" in check.detail
    assert "unset SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT" in check.remedy
    # Plenty of GiB and above both percents: admitted.
    assert _sized(400, 1858, both).state is DiskState.OK
    # Above the percent but under the GiB floor: still refused.
    assert _sized(10, 100, both).state is DiskState.CRITICAL


def test_a_percent_floor_alone_degrades_without_refusing() -> None:
    thresholds = DiskThresholds.from_gib(
        refuse_admission_below_gib=12.0,
        degraded_below_gib=24.0,
        refuse_basis="test",
        degraded_below_percent=15.0,
    )

    assert _sized(100, 1000, thresholds).state is DiskState.LOW
