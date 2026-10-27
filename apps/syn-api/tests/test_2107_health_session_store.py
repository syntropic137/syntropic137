"""#2107: /health reports the session archive's size, growth per day and runway."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import TYPE_CHECKING

import pytest

from syn_api.services import health_probes
from syn_api.types import Ok

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


async def test_the_cache_expires_after_its_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_probes, "_session_store_cache", health_probes._SessionStoreCache())
    clock = [1_800_000_000.0]
    monkeypatch.setattr(health_probes.time, "time", lambda: clock[0])
    walks: list[float] = []

    def measure(root: Path, now: float) -> None:
        walks.append(now)

    monkeypatch.setattr(health_probes, "_measure_session_store", measure)
    await health_probes.describe_session_store()
    clock[0] += health_probes.SESSION_STORE_CACHE_SECONDS - 1
    await health_probes.describe_session_store()
    clock[0] += 2
    await health_probes.describe_session_store()
    assert len(walks) == 2


async def test_concurrent_calls_share_one_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_probes, "_session_store_cache", health_probes._SessionStoreCache())
    walks: list[float] = []
    release = threading.Event()

    def measure(root: Path, now: float) -> None:
        walks.append(now)
        release.wait(5)

    monkeypatch.setattr(health_probes, "_measure_session_store", measure)
    first = asyncio.create_task(health_probes.describe_session_store())
    await asyncio.sleep(0.05)
    assert await health_probes.describe_session_store() is None
    release.set()
    await first
    assert len(walks) == 1


async def test_the_health_payload_carries_the_session_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_api.services import lifecycle
    from syn_shared.settings import get_settings

    (tmp_path / ("a" * 64)).write_bytes(b"x" * 10)
    monkeypatch.setenv("SYN_SESSION_INVENTORY_ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(health_probes, "_session_store_cache", health_probes._SessionStoreCache())
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        result = await lifecycle.health_check()
    finally:
        monkeypatch.delenv("SYN_SESSION_INVENTORY_ARCHIVE_DIR")
        get_settings.cache_clear()  # type: ignore[attr-defined]
    assert isinstance(result, Ok)
    store = result.value.model_dump(mode="json")["session_store"]
    assert (store["path"], store["object_count"], store["stored_bytes"]) == (str(tmp_path), 1, 10)
