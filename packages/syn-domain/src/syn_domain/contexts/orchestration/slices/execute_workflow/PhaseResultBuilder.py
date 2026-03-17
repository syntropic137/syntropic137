"""Phase result construction helpers for workflow execution.

Static factory methods for building PhaseResult in success/failure paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseResult,
    PhaseStatus,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
    )


class PhaseResultBuilder:
    """Factory methods for constructing PhaseResult."""

    @staticmethod
    def success(
        phase_id: str,
        started_at: datetime,
        session_id: str,
        artifact_ids: list[str],
        tokens: TokenAccumulator,
        warnings: list[str] | None = None,
    ) -> PhaseResult:
        """Build a successful PhaseResult.

        Args:
            warnings: Optional health signals (e.g. "zero_tokens", "no_artifacts").
                      Stored in metadata["warnings"] for dashboard display.
        """
        completed_at = datetime.now(UTC)
        metadata: dict[str, object] = {}
        if warnings:
            metadata["warnings"] = warnings
        return PhaseResult(
            phase_id=phase_id,
            status=PhaseStatus.COMPLETED,
            started_at=started_at,
            completed_at=completed_at,
            artifact_id=artifact_ids[0] if artifact_ids else None,
            session_id=session_id,
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            total_tokens=tokens.total_tokens,
            cost_usd=tokens.estimate_cost(),
            metadata=metadata,
        )

    @staticmethod
    def failure(
        phase_id: str,
        started_at: datetime,
        session_id: str,
        error_message: str,
    ) -> PhaseResult:
        """Build a failed PhaseResult."""
        return PhaseResult(
            phase_id=phase_id,
            status=PhaseStatus.FAILED,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            session_id=session_id,
            error_message=error_message,
        )
