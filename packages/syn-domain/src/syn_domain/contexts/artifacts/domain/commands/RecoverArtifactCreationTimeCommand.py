"""RecoverArtifactCreationTime command - fills a null creation time."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs it at runtime

from event_sourcing import command
from pydantic import BaseModel, ConfigDict


@command("RecoverArtifactCreationTime", "Fills an artifact's missing creation time")
class RecoverArtifactCreationTimeCommand(BaseModel):
    """Command to record a creation time recovered from the artifact's own record.

    Carries no "force" or "overwrite" option, deliberately. The only legitimate
    use is filling a null; an artifact that already states when it was created
    is the authority on the matter, and a command that could overwrite that
    would make the backfill capable of destroying the data it exists to
    complete.
    """

    model_config = ConfigDict(frozen=True)

    aggregate_id: str
    created_at: datetime
    recovered_from: str
