"""Get Installation query handler.

Handles the GetInstallationQuery by reading from the projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aef_domain.contexts.github.slices.get_installation.projection import (
    get_installation_projection,
)

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.queries.get_installation import (
        GetInstallationQuery,
    )
    from aef_domain.contexts.github.domain.read_models.installation import Installation


class GetInstallationHandler:
    """Handler for GetInstallationQuery.

    Reads from the installation projection to return the current state.
    """

    def handle(self, query: GetInstallationQuery) -> Installation | None:
        """Handle the query.

        Args:
            query: The GetInstallationQuery.

        Returns:
            Installation if found, None otherwise.
        """
        projection = get_installation_projection()
        return projection.get(query.installation_id)


# Singleton handler instance
_handler: GetInstallationHandler | None = None


def get_handler() -> GetInstallationHandler:
    """Get the query handler instance."""
    global _handler
    if _handler is None:
        _handler = GetInstallationHandler()
    return _handler


def reset_handler() -> None:
    """Reset the handler (for testing)."""
    global _handler
    _handler = None
