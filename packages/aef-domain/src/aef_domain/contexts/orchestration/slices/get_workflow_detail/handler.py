"""Handler for get_workflow_detail query."""

from aef_domain.contexts.orchestration.domain.queries.get_workflow_detail import (
    GetWorkflowDetailQuery,
)
from aef_domain.contexts.orchestration.domain.read_models.workflow_detail import (
    WorkflowDetail,
)

from .projection import WorkflowDetailProjection


class GetWorkflowDetailHandler:
    """Query Handler for get_workflow_detail.

    This handler retrieves detailed workflow data from the WorkflowDetailProjection.
    """

    def __init__(self, projection: WorkflowDetailProjection):
        self.projection = projection

    async def handle(self, query: GetWorkflowDetailQuery) -> WorkflowDetail | None:
        """Handle GetWorkflowDetailQuery."""
        return await self.projection.get_by_id(query.workflow_id)
