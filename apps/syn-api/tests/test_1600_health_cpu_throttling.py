"""/health reports control-plane CPU throttling from the cgroup (#1600).

Asserted on the /health PAYLOAD, not just on the parser: a counter read
correctly and dropped by the response model is the failure this guards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_api.services.cpu_throttling import read_cpu_throttling
from syn_api.types import Ok

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: A real cgroup v2 cpu.stat from a container with a CPU limit. The throttling
#: numbers are deliberately unlike anything a default could produce.
_CPU_STAT_V2 = """usage_usec 918273645
user_usec 700000000
system_usec 218273645
nr_periods 48211
nr_throttled 7193
throttled_usec 551234987
nr_bursts 0
burst_usec 0
"""

#: cpu.stat of a cgroup whose cpu controller is not enabled: usage only.
_CPU_STAT_NO_CONTROLLER = "usage_usec 1000\nuser_usec 600\nsystem_usec 400\n"


def test_counters_are_read_from_cgroup_v2(tmp_path: Path) -> None:
    stat = tmp_path / "cpu.stat"
    stat.write_text(_CPU_STAT_V2)

    result = read_cpu_throttling(stat)

    assert result.status == "measured"
    assert (result.nr_periods, result.nr_throttled, result.throttled_usec) == (
        48211,
        7193,
        551234987,
    )


def test_missing_file_is_unknown_not_zero(tmp_path: Path) -> None:
    """cgroup v1, or no container at all: there is no /sys/fs/cgroup/cpu.stat."""
    result = read_cpu_throttling(tmp_path / "absent" / "cpu.stat")

    assert result.status == "unknown"
    assert result.nr_throttled is None
    assert result.throttled_usec is None


def test_no_cpu_controller_is_unknown(tmp_path: Path) -> None:
    stat = tmp_path / "cpu.stat"
    stat.write_text(_CPU_STAT_NO_CONTROLLER)

    assert read_cpu_throttling(stat).status == "unknown"


async def test_health_payload_carries_the_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stat = tmp_path / "cpu.stat"
    stat.write_text(_CPU_STAT_V2)
    from syn_api.services import cpu_throttling, lifecycle

    monkeypatch.setattr(cpu_throttling, "read_cpu_throttling", lambda: read_cpu_throttling(stat))

    result = await lifecycle.health_check()
    assert isinstance(result, Ok)
    payload = result.value.model_dump(mode="json")

    assert payload["cpu_throttling"] == {
        "status": "measured",
        "nr_periods": 48211,
        "nr_throttled": 7193,
        "throttled_usec": 551234987,
    }
