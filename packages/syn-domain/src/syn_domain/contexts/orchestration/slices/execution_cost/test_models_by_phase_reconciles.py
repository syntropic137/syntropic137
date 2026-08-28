"""sum(models_by_phase[p]) must equal cost_by_phase[p] (#895, #931).

The breakdown exists to DECOMPOSE the phase total. A row that is priced but
names no model still spent money, and omitting it made the parts sum to less
than the whole - the same reconciliation failure #812 fixed for phases.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.orchestration.domain.read_models.execution_cost import (
    UNATTRIBUTED_MODEL,
)
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    price_phase_rows,
)

pytestmark = pytest.mark.unit


class _Row(dict):
    """asyncpg.Record is Mapping-like; a dict is enough for price_phase_rows."""

    def __getitem__(self, k: str) -> object:
        return self.get(k)


def _row(phase: str, model: str | None, sdk_cost: str | None) -> _Row:
    return _Row(
        phase_id=phase,
        model=model,
        total_input=0,
        total_output=0,
        cache_creation=0,
        cache_read=0,
        sdk_cost=Decimal(sdk_cost) if sdk_cost is not None else None,
        observation_count=1,
    )


class _Calc:
    def calculate_cost(self, *_a: object, **_k: object) -> Decimal:
        return Decimal("0")


def test_an_authoritative_cost_with_no_model_still_appears_in_the_breakdown() -> None:
    result = price_phase_rows([_row("p1", None, "1.25")], _Calc())

    assert result.cost_by_phase["p1"] == Decimal("1.25")
    assert result.models_by_phase["p1"] == {UNATTRIBUTED_MODEL: Decimal("1.25")}


def test_the_parts_sum_to_the_whole_for_every_priced_phase() -> None:
    rows = [
        _row("p1", "claude-sonnet-5", "0.03"),
        _row("p1", "gpt-5.6-sol", "0.19"),
        _row("p1", None, "0.01"),
        _row("p2", "claude-sonnet-5", "0.05"),
    ]
    result = price_phase_rows(rows, _Calc())

    for phase, total in result.cost_by_phase.items():
        assert sum(result.models_by_phase[phase].values()) == total, (
            f"{phase}: breakdown does not decompose the total"
        )
