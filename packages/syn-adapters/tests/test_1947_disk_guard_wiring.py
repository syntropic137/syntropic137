"""The real disk guard factory derives GiB floors from settings (#1947).

Constructs `build_disk_space_guard` itself, so a broken wiring between
`DiskSettings`, `SYN_EXECUTION_MAX_CONCURRENT` and the guard fails here rather
than on a self-host user's first run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.disk_space import build_disk_space_guard
from syn_domain.contexts._shared.disk_space import GIB
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

_DISK_ENV = (
    "SYN_DISK_DEGRADED_BELOW_PERCENT",
    "SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT",
    "SYN_DISK_DEGRADED_BELOW_GIB",
    "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB",
    "SYN_DISK_RUN_RESERVE_GIB",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[pytest.MonkeyPatch]:
    for name in _DISK_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYN_DISK_PATH", str(tmp_path))
    reset_settings()
    yield monkeypatch
    reset_settings()


def test_the_default_floors_scale_with_max_concurrent(env: pytest.MonkeyPatch) -> None:
    env.setenv("SYN_EXECUTION_MAX_CONCURRENT", "20")
    reset_settings()

    check = build_disk_space_guard().check()

    assert check.thresholds.refuse_admission_below_bytes == 60 * GIB
    assert check.thresholds.degraded_below_bytes == 120 * GIB
    assert check.thresholds.refuse_admission_below_percent is None
    assert "SYN_EXECUTION_MAX_CONCURRENT=20" in check.thresholds.refuse_basis


def test_the_pre_1947_percent_env_vars_still_reach_the_guard(env: pytest.MonkeyPatch) -> None:
    env.setenv("SYN_DISK_DEGRADED_BELOW_PERCENT", "15")
    env.setenv("SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT", "5")
    env.setenv("SYN_DISK_REFUSE_ADMISSION_BELOW_GIB", "10")
    reset_settings()

    thresholds = build_disk_space_guard().check().thresholds

    assert thresholds.refuse_admission_below_percent == 5.0
    assert thresholds.degraded_below_percent == 15.0
    assert thresholds.refuse_admission_below_bytes == 10 * GIB
    assert thresholds.refuse_basis == "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB"
    # With an explicit floor, lowering the run reserve would do nothing.
    assert thresholds.lower_floor_with == "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB"
