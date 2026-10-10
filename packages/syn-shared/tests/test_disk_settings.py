"""SYN_DISK_* settings (#1560)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from syn_shared.settings.disk import DiskSettings

pytestmark = pytest.mark.unit


def test_defaults_degrade_at_fifteen_refuse_at_five_reclaim_after_six_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "SYN_DISK_DEGRADED_BELOW_PERCENT",
        "SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT",
        "SYN_DISK_RECLAIM_GRACE_HOURS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = DiskSettings(_env_file=None)
    # PC-130: 10% paged too late to reclaim by hand before admission closed.
    assert settings.degraded_below_percent == 15.0
    assert settings.refuse_admission_below_percent == 5.0
    assert settings.reclaim_grace_hours == 6.0


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
