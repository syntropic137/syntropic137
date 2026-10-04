"""RequestExecution command (#1557)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts._shared.repository_ref import (
    RepositoryRef,  # noqa: TC001 - runtime field type
)
from syn_domain.contexts.orchestration._shared.tags import TagSet


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

    @property
    def aggregate_id(self) -> str:
        return self.execution_id
