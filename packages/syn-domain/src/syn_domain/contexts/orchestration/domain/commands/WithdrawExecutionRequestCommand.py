"""WithdrawExecutionRequest command (#1650)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration.domain.aggregate_execution_request.value_objects import (
    execution_request_id,
)


@command("WithdrawExecutionRequest", "Withdraws an admitted direct start that has not started")
class WithdrawExecutionRequestCommand(BaseModel):
    """Withdraw the request that names ``execution_id``, so it never starts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str = Field(..., min_length=1)
    reason: str | None = None

    @property
    def aggregate_id(self) -> str:
        """The request's own id, never ``execution_id``: one id is one stream."""
        return execution_request_id(self.execution_id)
