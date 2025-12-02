"""List Workflows Query Handler.

This handler processes ListWorkflowsQuery requests and returns
WorkflowSummary data from the projection.
"""

from aef_domain.contexts.workflows.domain.queries import ListWorkflowsQuery
from aef_domain.contexts.workflows.domain.read_models import WorkflowSummary

from .projection import WorkflowListProjection


class ListWorkflowsHandler:
    """Handles ListWorkflowsQuery requests.

    This handler retrieves workflow data from the WorkflowListProjection.
    It is the primary interface for listing workflows.
    """

    def __init__(self, projection: WorkflowListProjection):
        """Initialize with a projection.

        Args:
            projection: The WorkflowListProjection to query
        """
        self._projection = projection

    async def handle(self, query: ListWorkflowsQuery) -> list[WorkflowSummary]:
        """Handle a ListWorkflowsQuery.

        Args:
            query: The query parameters

        Returns:
            List of WorkflowSummary matching the query
        """
        return await self._projection.query(
            status_filter=query.status_filter,
            workflow_type_filter=query.workflow_type_filter,
            limit=query.limit,
            offset=query.offset,
            order_by=query.order_by,
        )
