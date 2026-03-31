"""UpdateArtifact command - updates mutable artifact metadata."""

from __future__ import annotations

from typing import Any

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, model_validator


@command("UpdateArtifact", "Updates mutable artifact metadata")
class UpdateArtifactCommand(BaseModel):
    """Command to update an artifact's mutable fields.

    Only title, metadata, and is_primary_deliverable are mutable.
    Content and artifact_type are immutable (event-sourced audit trail).
    """

    model_config = ConfigDict(frozen=True)

    aggregate_id: str

    title: str | None = None
    metadata: dict[str, Any] | None = None
    is_primary_deliverable: bool | None = None

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> UpdateArtifactCommand:
        """Ensure at least one field to update is provided."""
        if self.title is None and self.metadata is None and self.is_primary_deliverable is None:
            raise ValueError("at least one field to update is required")
        return self
