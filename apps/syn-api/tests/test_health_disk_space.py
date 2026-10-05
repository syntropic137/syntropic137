"""/health reports the workspace volume's free space and degrades when it is low (#1560)."""

from __future__ import annotations

import typing

import pytest

from syn_api.services import lifecycle
from syn_api.services.degraded_reasons import DegradedReason
from syn_api.types import DiskSpaceHealth, HealthResponse, Ok
from syn_domain.contexts._shared.disk_space import DiskSpaceGuard, DiskState, DiskUsage

pytestmark = pytest.mark.unit


class _FakeDisk:
    def __init__(self, free_percent: float) -> None:
        self._free_percent = free_percent

    @property
    def path(self) -> str:
        return "/workspaces"

    def usage(self) -> DiskUsage:
        return DiskUsage(free_bytes=int(1000 * self._free_percent / 100), total_bytes=1000)


def _use_disk(monkeypatch: pytest.MonkeyPatch, free_percent: float) -> None:
    guard = DiskSpaceGuard(
        _FakeDisk(free_percent), degraded_below_percent=10.0, refuse_admission_below_percent=5.0
    )
    monkeypatch.setattr("syn_api._wiring_admission.get_disk_space_guard", lambda: guard)


async def _health() -> HealthResponse:
    result = await lifecycle.health_check()
    assert isinstance(result, Ok)
    return result.value


async def test_low_disk_degrades_health_and_says_how_much_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_disk(monkeypatch, 7.0)
    health = await _health()

    assert health.mode == "degraded"
    assert DegradedReason.DISK_SPACE in (health.degraded_reasons or [])
    assert health.disk == DiskSpaceHealth(
        path="/workspaces",
        state="low",
        free_percent=7.0,
        free_bytes=70,
        degraded_below_percent=10.0,
        refuse_admission_below_percent=5.0,
    )
    # And it reaches the wire, not just the model.
    assert health.model_dump(mode="json")["disk"]["state"] == "low"


async def test_plenty_of_disk_raises_no_disk_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_disk(monkeypatch, 50.0)
    health = await _health()

    assert DegradedReason.DISK_SPACE not in (health.degraded_reasons or [])
    assert health.disk is not None
    assert health.disk.state == "ok"


def test_the_published_states_are_the_guards_states() -> None:
    """The wire Literal restates `DiskState`; this keeps the two from drifting."""
    published = set(typing.get_args(DiskSpaceHealth.model_fields["state"].annotation))
    assert published == {state.value for state in DiskState}
