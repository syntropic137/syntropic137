"""RequestExecution command (#1557)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts._shared.repository_ref import (
    RepositoryRef,  # noqa: TC001 - runtime field type
)
from syn_domain.contexts.orchestration._shared.eval_choice import LaunchEval  # noqa: TC001
from syn_domain.contexts.orchestration._shared.repository_baseline import (
    RepositoryBaseline,
)
from syn_domain.contexts.orchestration._shared.tags import TagSet
from syn_domain.contexts.orchestration.domain.aggregate_execution_request.value_objects import (
    execution_request_id,
)


@command("RequestExecution", "Records an admitted direct start before it runs")
class RequestExecutionCommand(BaseModel):
    """Record that a direct start of ``workflow_id`` was admitted as ``execution_id``."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    execution_id: str = Field(..., min_length=1)
    workflow_id: str = Field(..., min_length=1)
    inputs: dict[str, str] = Field(default_factory=dict)
    task: str | None = None
    repos: list[RepositoryRef] = Field(default_factory=list)
    tags: TagSet = Field(default_factory=TagSet)
    launch_eval: LaunchEval
    """The eval the start joins and its frozen baseline (#967), resolved and
    admitted at acceptance (``launch_eval_for``) and never again: a start that
    waits for a slot, or is recovered after a restart, still joins this one."""

    @property
    def aggregate_id(self) -> str:
        """The request's own id, never ``execution_id``: one id is one stream."""
        return execution_request_id(self.execution_id)


# As `ExecuteWorkflowCommand`: `LaunchEval.baseline` names `RepositoryBaseline`
# only under TYPE_CHECKING, so pydantic is given the name here.
RequestExecutionCommand.model_rebuild(_types_namespace={"RepositoryBaseline": RepositoryBaseline})
