"""#2107: /health reports the session archive's size, growth per day and runway."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import pytest

from syn_api.services import health_probes

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

DAY = 86_400.0


def test_growth_rate_and_runway(tmp_path: Path) -> None:
    now = time.time()
    for name, size, age in (("a" * 64, 7 << 20, 0.5), ("b" * 64, 7 << 20, 5), ("c" * 64, 1, 40)):
        (tmp_path / name).write_bytes(b"x" * size)
        os.utime(tmp_path / name, (now - age * DAY, now - age * DAY))
    health = health_probes._measure_session_store(tmp_path, now)
    assert health is not None
    assert health.object_count == 3
    assert health.added_bytes_24h == 7 << 20
    assert health.added_bytes_per_day_7d == (14 << 20) // 7
    assert health.days_until_full == pytest.approx(
        health.filesystem_free_bytes / health.added_bytes_per_day_7d, abs=0.1
    )
    assert "2.0 MiB/day over 7d" in health.detail and "days at that rate" in health.detail


def test_no_recent_growth_has_no_runway(tmp_path: Path) -> None:
    (tmp_path / ("a" * 64)).write_bytes(b"x")
    os.utime(tmp_path / ("a" * 64), (0, 0))
    health = health_probes._measure_session_store(tmp_path, time.time())
    assert health is not None and health.days_until_full is None
    assert "days at that rate" not in health.detail


async def test_the_walk_is_cached_and_a_failure_is_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_probes, "_session_store_cache", health_probes._SessionStoreCache())
    walks: list[Path] = []

    def measure(root: Path, now: float) -> None:
        walks.append(root)
        raise OSError("unreadable")

    monkeypatch.setattr(health_probes, "_measure_session_store", measure)
    assert await health_probes.describe_session_store() is None
    assert await health_probes.describe_session_store() is None
    assert len(walks) == 1
