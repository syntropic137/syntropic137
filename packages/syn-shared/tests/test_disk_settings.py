"""SYN_DISK_* settings (#1560)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_shared.settings.disk import DiskSettings

pytestmark = pytest.mark.unit


_DISK_ENV = (
    "SYN_DISK_DEGRADED_BELOW_PERCENT",
    "SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT",
    "SYN_DISK_DEGRADED_BELOW_GIB",
    "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB",
    "SYN_DISK_RUN_RESERVE_GIB",
    "SYN_DISK_RECLAIM_SETTLE_MINUTES",
    "SYN_DISK_RECLAIM_DRY_RUN",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _DISK_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_judge_on_gib_alone_and_reclaim_ten_minutes_after_terminal(
    clean_env: pytest.MonkeyPatch,
) -> None:
    settings = DiskSettings(_env_file=None)
    # #1947: no percent floor by default; a percent of a large disk is too much.
    assert settings.degraded_below_percent is None
    assert settings.refuse_admission_below_percent is None
    assert settings.run_reserve_gib == 3.0
    assert settings.reclaim_settle_minutes == 10.0
    assert settings.reclaim_dry_run is False


@pytest.mark.parametrize(
    ("max_concurrent", "refuse", "degraded"),
    [(1, 3.0, 6.0), (4, 12.0, 24.0), (20, 60.0, 120.0), (100, 300.0, 600.0)],
)
def test_the_default_floor_is_one_run_reserve_per_concurrent_run(
    clean_env: pytest.MonkeyPatch, max_concurrent: int, refuse: float, degraded: float
) -> None:
    settings = DiskSettings(_env_file=None)
    assert settings.admission_floor_gib(max_concurrent) == refuse
    assert settings.degraded_floor_gib(max_concurrent) == degraded
    assert f"SYN_EXECUTION_MAX_CONCURRENT={max_concurrent}" in settings.admission_floor_basis(
        max_concurrent
    )


def test_explicit_gib_floors_win_over_the_derived_ones(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SYN_DISK_REFUSE_ADMISSION_BELOW_GIB", "5")
    clean_env.setenv("SYN_DISK_DEGRADED_BELOW_GIB", "8")
    settings = DiskSettings(_env_file=None)
    assert settings.admission_floor_gib(100) == 5.0
    assert settings.degraded_floor_gib(100) == 8.0
    assert settings.admission_floor_basis(100) == "SYN_DISK_REFUSE_ADMISSION_BELOW_GIB"


def test_a_degraded_gib_below_the_derived_admission_floor_is_raised_to_it(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Refusing while /health says ok is the silent refusal #1560 replaced."""
    clean_env.setenv("SYN_DISK_DEGRADED_BELOW_GIB", "5")
    settings = DiskSettings(_env_file=None)
    assert settings.degraded_floor_gib(4) == 12.0


def test_a_gib_floor_above_the_gib_warning_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DiskSettings(_env_file=None, degraded_below_gib=5.0, refuse_admission_below_gib=10.0)


def test_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_DISK_DEGRADED_BELOW_PERCENT", "20")
    monkeypatch.setenv("SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT", "8")
    monkeypatch.setenv("SYN_DISK_PATH", "/data")
    settings = DiskSettings(_env_file=None)
    assert (settings.degraded_below_percent, settings.refuse_admission_below_percent) == (20, 8)
    assert settings.path == "/data"


def test_a_floor_above_the_warning_threshold_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DiskSettings(
            _env_file=None, degraded_below_percent=5.0, refuse_admission_below_percent=10.0
        )


def test_empty_values_from_a_copied_env_example_mean_unset(clean_env: pytest.MonkeyPatch) -> None:
    for name in _DISK_ENV[:4]:
        clean_env.setenv(name, "")
    settings = DiskSettings(_env_file=None)
    assert settings.refuse_admission_below_gib is None
    assert settings.refuse_admission_below_percent is None
    assert settings.admission_floor_gib(4) == 12.0
