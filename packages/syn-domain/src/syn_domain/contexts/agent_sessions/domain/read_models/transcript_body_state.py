"""Current restrictions on exact local bodies, separate from historical receipts."""

from typing import Literal

from pydantic import Field

from .session_inventory import InventoryModel


class TranscriptBodyState(InventoryModel):
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["expired", "withheld"]
