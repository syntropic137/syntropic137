"""Query for retrieving execution cost."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GetExecutionCostQuery:
    """Query to get aggregated cost for a workflow execution.

    Attributes:
        execution_id: The execution to get cost for.
        include_breakdown: Whether to include phase/model/tool breakdowns.
        include_session_ids: Whether to include the list of session IDs.
    """

    execution_id: str
    include_breakdown: bool = True
    include_session_ids: bool = False
