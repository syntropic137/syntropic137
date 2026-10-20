"""``TurnCost`` as the session-cost projection document stores it (#1420).

Replay keeps what a session's turns priced to apart from what a summary
settled, under its own key in the projection document. Reading it back is a
trust boundary - the document comes from the store, not from this process -
so it is validated here, and a malformed one fails loudly instead of pricing
a session from whatever happened to be there.

The model lives outside the projection module because projections may import
stdlib, the framework and the domain, and nothing else (VSA032, ``vsa.yaml``).
"""

from __future__ import annotations

from decimal import Decimal  # noqa: TC003 - Pydantic resolves it at runtime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, TypeAdapter

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.slices.session_cost.unreported_cost import TurnCost

#: Projection-document key for what the session's turns alone priced to.
TURN_COST_KEY = "turn_cost"


class StoredTurnCost(BaseModel):
    """``TurnCost`` as the projection document stores it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: Decimal
    cost_by_model: dict[str, Decimal]
    unpriced_observation_count: int

    @classmethod
    def of(cls, turns: TurnCost) -> StoredTurnCost:
        return cls(
            total=turns.total,
            cost_by_model=dict(turns.cost_by_model),
            unpriced_observation_count=turns.unpriced_observation_count,
        )


#: Reads the stored turn cost back, and absence as ``None``, not as an error.
STORED_TURN_COST = TypeAdapter(StoredTurnCost | None)
