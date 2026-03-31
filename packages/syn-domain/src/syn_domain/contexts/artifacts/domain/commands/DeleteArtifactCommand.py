"""DeleteArtifact command - soft-deletes an artifact."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, field_validator


@command("DeleteArtifact", "Soft-deletes an artifact")
class DeleteArtifactCommand(BaseModel):
    """Command to soft-delete an artifact.

    Deleted artifacts are hidden from listings but preserved
    in the event store for historical reference.
    """

    model_config = ConfigDict(frozen=True)

    aggregate_id: str
    deleted_by: str = ""

    @field_validator("aggregate_id")
    @classmethod
    def validate_aggregate_id(cls, v: str) -> str:
        """Ensure aggregate_id is provided."""
        if not v:
            raise ValueError("aggregate_id is required")
        return v
