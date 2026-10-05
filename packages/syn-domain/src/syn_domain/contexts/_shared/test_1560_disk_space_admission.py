"""A nearly-full workspace volume refuses admission instead of failing mid-write (#1560).

Measured through a fake port: no test here touches a real filesystem.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts._shared.disk_space import (
    DiskSpaceGuard,
    DiskState,
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


def _guard(free_percent: float | None) -> DiskSpaceGuard:
    return DiskSpaceGuard(
        _FakeDisk(free_percent), degraded_below_percent=10.0, refuse_admission_below_percent=5.0
    )


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

    assert "3.0% free on /workspaces" in str(refused.value)
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
