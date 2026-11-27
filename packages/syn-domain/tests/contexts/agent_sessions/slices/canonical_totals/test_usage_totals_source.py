"""The session-grain UsageTotalsSource, priced by _sum_groups, is today's totals (ADR-079 D8).

Slice 2 put a port between where the pricing groups come from and how they
are priced, so a later source can keep the sums elsewhere. The first source is
today's SQL. These tests hold it to the reader /metrics served before #2341,
and pin where it puts a group's reported turns: on the group pricing left
unpriced, which is the one place _sum_groups reads them.
"""

from __future__ import annotations

import dataclasses

import pytest

from syn_domain.contexts.agent_sessions import CostCalculator
from syn_domain.contexts.agent_sessions.slices.canonical_totals.query_service import (
    PricingGroupRow,
    SessionGrainUsageSource,
)

from .test_897_canonical_totals_coverage import (
    RATED,
    UNRATED,
    _Cell,
    _Conn,
    _group,
    _Pool,
    _service,
    _turns,
)
from .test_2341_turn_sessions_are_bounded import _frozen_reader, _zero_total

pytestmark = pytest.mark.unit


def _totals() -> list[dict[str, _Cell]]:
    """A priced group, an unrated model with and without a vendor cost, and a zero total."""
    return [
        _group(RATED, vendor_cost=None, summary_observations=2, turn_sessions=["r-1"]),
        _group(UNRATED, vendor_cost="0.25", summary_observations=1, turn_sessions=None),
        _group(UNRATED, vendor_cost=None, summary_observations=1, turn_sessions=["u-1", "u-2"]),
        _zero_total("mystery-model-2", ["zero-only"]),
    ]


def _conn() -> _Conn:
    return _Conn(
        totals=_totals(),
        turns=[_turns(UNRATED, 3), _turns("mystery-model-2", 2)],
    )


@pytest.mark.parametrize("execution_ids", [None, {"exec-1"}])
async def test_the_source_priced_by_sum_groups_is_the_frozen_readers_totals(
    execution_ids: set[str] | None,
) -> None:
    service = _service(_conn())
    source = SessionGrainUsageSource(
        CostCalculator(), sorted(execution_ids) if execution_ids is not None else None
    )

    groups = await source.group_rows(_conn())  # type: ignore[arg-type]  # the #897 double
    priced = service._sum_groups(groups)  # the half of totals() the port feeds
    before = (
        await _frozen_reader()
        .PreBoundCanonicalUsageQueryService(_Pool(_conn()), CostCalculator())
        .totals(execution_ids=execution_ids)
    )

    expected = {**dataclasses.asdict(before), "sessions": 0}
    assert dataclasses.asdict(priced) == expected
    # The unpriced group's summary and its 3 reported turns; the zero total's
    # 2 are never counted, and the vendor-costed group is priced.
    assert priced.unpriced_observation_count == 1 + 3
    # And totals(), which reads through the same source, agrees.
    served = await _service(_conn()).totals(execution_ids=execution_ids)
    assert dataclasses.asdict(served) == {**expected, "sessions": 1}


async def test_reported_turns_land_on_the_unpriced_group_alone() -> None:
    groups = await SessionGrainUsageSource(CostCalculator(), None).group_rows(_conn())  # type: ignore[arg-type]  # the #897 double

    reported = {
        (group.model, group.vendor_cost_usd is None): group.reported_observations
        for group in groups
    }
    assert reported == {
        (RATED, True): 0,
        (UNRATED, False): 0,
        (UNRATED, True): 3,
        ("mystery-model-2", True): 0,
    }
    assert all(isinstance(group, PricingGroupRow) for group in groups)
