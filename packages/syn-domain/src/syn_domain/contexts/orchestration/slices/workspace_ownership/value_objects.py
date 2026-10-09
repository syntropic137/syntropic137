"""The typed stored row for durable workspace ownership (PC-130)."""

from pydantic import BaseModel, ConfigDict


class WorkspaceOwner(BaseModel):
    """The executions recorded for a workspace; ambiguity must protect it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    execution_ids: tuple[str, ...]
