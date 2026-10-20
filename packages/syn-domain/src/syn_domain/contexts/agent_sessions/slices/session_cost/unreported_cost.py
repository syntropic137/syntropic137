"""What a session costs when its ``session_summary`` reports no ``total_cost_usd`` (#1420).

A killed or timed-out run still emits a summary, carrying its token totals and
``total_cost_usd: null`` (#1164). Two readers answer for that session - the
replayed ``SessionCostProjection`` and the TimescaleDB query path - and they
used to answer differently: replay kept what the turns had priced, SQL
re-priced the summary's own totals under the summary's single model. This
module is the one rule both now apply.

THE RULE. The cost is what the session's ``token_usage`` turns priced to, each
at its own model (#788): the same total, the same per-model breakdown, the same
unpriced count. The summary is never re-priced, because its single model is
wrong for any session that spanned two, and nothing here drops to $0.00 just
because the harness did not get to say (#1164).

The TOKENS still come from the summary - it is the harness's cumulative count,
and per-turn deltas over-count re-sent context. So for such a session the
tokens and the cost have different sources, deliberately: the cost is the best
priced estimate available, and ``is_finalized`` already says it is not a bill.

One case has no turns to price: a summary with tokens and no observation at
all. Its cost is unknown, so it is reported as zero dollars LABELLED unpriced
(one unpriced observation, the summary itself), never as a bare $0.00 that
reads as free work (#890).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class TurnCost:
    """What a session's turns priced to, each at its own model."""

    total: Decimal = Decimal("0")
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    unpriced_observation_count: int = 0

    @property
    def observed_any_turn(self) -> bool:
        """Every turn either priced into a model's entry or counted as unpriced."""
        return bool(self.cost_by_model) or self.unpriced_observation_count > 0


def cost_under_unreported_summary(turns: TurnCost, summary_tokens: int) -> TurnCost:
    """The session's cost once a summary with no ``total_cost_usd`` arrives."""
    if turns.observed_any_turn or summary_tokens == 0:
        return turns
    return TurnCost(unpriced_observation_count=1)
