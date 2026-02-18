"""List Triggers query handler.

Handles the ListTriggersQuery by reading from the projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.github.slices.list_triggers.projection import (
    get_trigger_rule_projection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github.domain.queries.list_triggers import (
        ListTriggersQuery,
    )
    from syn_domain.contexts.github.domain.read_models.trigger_rule import TriggerRule


class ListTriggersHandler:
    """Handler for ListTriggersQuery.

    Reads from the trigger rule projection to return matching rules.
    """

    def handle(self, query: ListTriggersQuery) -> list[TriggerRule]:
        """Handle the query.

        Args:
            query: The ListTriggersQuery.

        Returns:
            List of matching TriggerRule read models.
        """
        projection = get_trigger_rule_projection()
        return projection.list_all(
            repository=query.repository,
            status=query.status,
        )


# Singleton
_handler: ListTriggersHandler | None = None


def get_list_triggers_handler() -> ListTriggersHandler:
    """Get the query handler instance."""
    global _handler
    if _handler is None:
        _handler = ListTriggersHandler()
    return _handler


def reset_list_triggers_handler() -> None:
    """Reset the handler (for testing)."""
    global _handler
    _handler = None
