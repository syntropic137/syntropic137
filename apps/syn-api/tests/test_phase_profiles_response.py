"""Phase profile percentiles and their display strings (#1716).

The end-to-end read is pinned by
``integration/test_phase_profiles_reach_the_api.py``; this pins the two rules
that test cannot isolate: the ten-phase threshold and the coverage counts
when no usage row exists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from syn_api.types import PhaseProfilesResponse
from syn_domain.contexts.orchestration.slices.phase_profiles import Percentiles, PhaseProfiles
from syn_domain.contexts.orchestration.slices.phase_profiles.query_service import (
    _resource_profiles,
)

pytestmark = pytest.mark.unit


def test_nine_phases_are_insufficient_and_ten_are_not() -> None:
    assert Percentiles.of(range(9)).p50 is None
    ten = Percentiles.of(range(1, 11))
    assert (ten.n, ten.p50, ten.p90) == (10, 5.5, pytest.approx(9.1))


def test_unmeasured_phases_are_counted_not_dropped() -> None:
    usage = json.dumps({"cpu_usage_seconds": 3.0, "memory_peak_bytes": None})
    rows = [{"phase_id": "plan", "wall_seconds": 30.0, "usage": usage}] + [
        {"phase_id": "plan", "wall_seconds": 30.0, "usage": None} for _ in range(4)
    ]
    now = datetime.now(UTC)
    profiles = PhaseProfiles(
        workflow_id="wf",
        since=now,
        until=now,
        executions=5,
        resources=_resource_profiles(rows),  # type: ignore[arg-type]  # Record stand-ins
    )

    body = PhaseProfilesResponse.from_profiles(profiles, window_days=7)

    (plan,) = body.resources
    assert plan.coverage.phases == 5
    assert plan.coverage.phases_without_usage_row == 4
    assert plan.coverage.memory_peak_bytes_missing == 1
    assert plan.coverage.coverage_display == "1/5 phases measured"
    assert plan.cpu_seconds_per_wall_second.n == 1
    assert plan.cpu_seconds_per_wall_second.p50_display == "insufficient"
