"""Phase profile percentiles and their display strings (#1716).

The end-to-end read is pinned by
``integration/test_phase_profiles_reach_the_api.py``; this pins the two rules
that test cannot isolate: the ten-phase threshold and the coverage counts
when no usage row exists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_api.types import PhaseProfilesResponse
from syn_domain.contexts.orchestration.slices.phase_profiles import Percentiles, PhaseProfiles
from syn_domain.contexts.orchestration.slices.phase_profiles.query_service import (
    _resource_profiles,
    _split_summary,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit


def test_nine_phases_are_insufficient_and_ten_are_not() -> None:
    assert Percentiles.of(range(9)).p50 is None
    ten = Percentiles.of(range(1, 11))
    assert (ten.n, ten.p50, ten.p90) == (10, 5.5, pytest.approx(9.1))


def test_unmeasured_phases_are_counted_not_dropped() -> None:
    usage = json.dumps(
        {"cpu_usage_seconds": 3.0, "memory_peak_bytes": None, "workspace_lifetime_seconds": 30.0}
    )
    no_lifetime = json.dumps({"cpu_usage_seconds": 3.0, "memory_peak_bytes": 1})
    rows = [{"phase_id": "plan", "usage": usage}, {"phase_id": "plan", "usage": no_lifetime}] + [
        {"phase_id": "plan", "usage": None} for _ in range(4)
    ]
    now = datetime.now(UTC)
    profiles = PhaseProfiles(
        workflow_id="wf",
        since=now,
        until=now,
        executions=6,
        resources=_resource_profiles(rows),  # type: ignore[arg-type]  # Record stand-ins
    )

    body = PhaseProfilesResponse.from_profiles(profiles, window_days=7)

    (plan,) = body.resources
    assert plan.coverage.phases == 6
    assert plan.coverage.phases_without_usage_row == 4
    assert plan.coverage.memory_peak_bytes_missing == 1
    assert plan.coverage.coverage_display == "2/6 phases measured"
    # A row without the workspace lifetime has CPU but no interval: no rate.
    assert plan.coverage.wall_seconds_missing == 1
    assert plan.cpu_seconds_per_wall_second.n == 1
    assert plan.cpu_seconds_per_wall_second.p50 is None
    assert plan.cpu_seconds_per_wall_second.p50_display == "insufficient"


OPUS = "claude-opus-5"
HAIKU = "claude-haiku-4-5-20251001"


class _Rate:
    def __init__(self, per_token: str) -> None:
        self._per_token = Decimal(per_token)

    def calculate_cost(
        self, input_tokens: int, output_tokens: int, cache_creation: int, cache_read: int
    ) -> Decimal:
        return self._per_token * (input_tokens + output_tokens + cache_creation + cache_read)


class _Rates:
    def resolve_pricing(self, model: str | None) -> _Rate | None:
        return {OPUS: _Rate("0.003"), HAIKU: _Rate("0.001")}.get(model or "")


def _usage(model: str, vendor: str | None, *tokens: int) -> Mapping[str, str | int | None]:
    categories = ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")
    return {"model": model, "vendor_cost_usd": vendor, **dict(zip(categories, tokens, strict=True))}


def test_a_mixed_model_summary_is_conserved_across_the_models_that_ran() -> None:
    """The production fallback shape: turns on two models, one summary on one (#1716)."""
    summary = _usage(OPUS, "0.80", 1800, 101, 7, 400)
    turns = [_usage(OPUS, None, 500, 1, 0, 100), _usage(HAIKU, None, 1300, 1, 0, 300)]

    shares = _split_summary(summary, turns, _Rates())  # type: ignore[arg-type]  # Record stand-ins

    by_model = {s.model: s for s in shares}
    assert set(by_model) == {OPUS, HAIKU}
    assert (by_model[OPUS].input_tokens, by_model[HAIKU].input_tokens) == (500, 1300)
    assert (by_model[OPUS].cache_read_tokens, by_model[HAIKU].cache_read_tokens) == (100, 300)
    for category in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"):
        assert sum(getattr(s, category) for s in shares) == summary[category], category
    # The vendor total is conserved, divided by what each share costs at its rate.
    assert sum(s.cost for s in shares) == Decimal("0.80")
    # Output 101 splits 51/50 as the turns did (1:1); cache writes, which no
    # turn reported, split 2/5 like the turns' tokens overall (601:1601).
    assert (by_model[OPUS].output_tokens, by_model[HAIKU].output_tokens) == (51, 50)
    assert (by_model[OPUS].cache_creation_tokens, by_model[HAIKU].cache_creation_tokens) == (2, 5)
    opus_rate = Decimal("0.003") * (500 + 51 + 2 + 100)
    haiku_rate = Decimal("0.001") * (1300 + 50 + 5 + 300)
    expected_opus = Decimal("0.80") * opus_rate / (opus_rate + haiku_rate)
    assert float(by_model[OPUS].cost) == pytest.approx(float(expected_opus))
    assert by_model[HAIKU].cost > 0
