"""Phase result construction helpers for workflow execution.

Static factory methods for building PhaseResult in success/failure paths.
"""

from __future__ import annotations

from datetime import UTC, datetime

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseResult,
    PhaseStatus,
)


class PhaseResultBuilder:
    """Factory methods for constructing PhaseResult."""

    @staticmethod
    def success(
        phase_id: str,
        started_at: datetime,
        session_id: str,
        artifact_ids: list[str],
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        total_tokens: int,
        warnings: list[str] | None = None,
    ) -> PhaseResult:
        """Build a successful PhaseResult.

        Token counts MUST be the authoritative final values (e.g. from Claude
        CLI's terminal `result` event when available), not cumulative streaming
        deltas — otherwise ExecutionMetrics.from_results double-counts.

        Cost is Lane 2 telemetry and is not carried on PhaseResult — see
        session_cost / execution_cost projections.

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
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            total_tokens=total_tokens,
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
