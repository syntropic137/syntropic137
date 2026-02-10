"""Trigger History query handler.

Handles the GetTriggerHistoryQuery by reading from the projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aef_domain.contexts.github.slices.trigger_history.projection import (
    get_trigger_history_projection,
)

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.queries.get_trigger_history import (
        GetTriggerHistoryQuery,
    )
    from aef_domain.contexts.github.domain.read_models.trigger_history_entry import (
        TriggerHistoryEntry,
    )


class GetTriggerHistoryHandler:
    """Handler for GetTriggerHistoryQuery.

    Reads from the trigger history projection.
    """

    def handle(self, query: GetTriggerHistoryQuery) -> list[TriggerHistoryEntry]:
        """Handle the query.

        Args:
            query: The GetTriggerHistoryQuery.

        Returns:
            List of TriggerHistoryEntry read models.
        """
        projection = get_trigger_history_projection()
        return projection.get_history(
            trigger_id=query.trigger_id,
            limit=query.limit,
        )


# Singleton
_handler: GetTriggerHistoryHandler | None = None


def get_trigger_history_handler() -> GetTriggerHistoryHandler:
    """Get the query handler instance."""
    global _handler
    if _handler is None:
        _handler = GetTriggerHistoryHandler()
    return _handler


def reset_trigger_history_handler() -> None:
    """Reset the handler (for testing)."""
    global _handler
    _handler = None
