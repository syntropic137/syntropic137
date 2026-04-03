"""Protocol for trigger evaluation — used by event_pipeline without cross-slice imports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_evaluation_types import (
        TriggerDeferredResult,
        TriggerMatchResult,
    )


class TriggerEvaluator(Protocol):
    """Interface for evaluating trigger rules against incoming events."""

    async def evaluate(
        self,
        event: str,
        repository: str,
        installation_id: str,
        payload: dict[str, Any],
    ) -> list[TriggerMatchResult | TriggerDeferredResult]: ...
