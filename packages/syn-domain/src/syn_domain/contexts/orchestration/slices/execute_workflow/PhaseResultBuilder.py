"""Phase result construction helpers for workflow execution.

Static factory methods for building PhaseResult in success/failure paths.
"""

from __future__ import annotations

from datetime import UTC, datetime

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseResult,
    PhaseStatus,
    PhaseUsage,
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
        completed_at: datetime | None = None,
        exit_code: int | None = None,
        artifact_id: str | None = None,
        usage: PhaseUsage | None = None,
    ) -> PhaseResult:
        """Build a failed PhaseResult.

        ``completed_at`` is accepted so the caller can pass the SAME instant it
        used to compute the phase's duration. Reading the clock again here made
        ``completed_at - started_at`` disagree with the recorded duration.

        ``exit_code`` defaults to None rather than to a number because most
        failures have no process behind them at all, and None says so (#1319).
        ``artifact_id`` names what was kept out of the phase before the run was
        torn down (#1321). A failed phase could carry no artifact at all, which
        is why a phase that wrote a 1322-line deliverable and then botched its
        ``TASK_RESULT`` showed ``artifact_ids: []``. It stays optional because
        most failures have nothing to point at.

        ``usage`` is what the phase had spent when it died (#1262). Omitting it
        is how this builder reported zeros for every failed phase ever run,
        while the numbers sat in the accumulator and in the exception's own
        message - so a stall and a genuine overrun both arrived as exit 124 with
        nothing to tell them apart. ``None`` means the caller has nothing to
        report rather than a phase that spent nothing; both render as zeros,
        because for tokens those are the same claim (see ``PhaseUsage``).
        """
        spent = usage or PhaseUsage()
        return PhaseResult(
            phase_id=phase_id,
            status=PhaseStatus.FAILED,
            started_at=started_at,
            completed_at=completed_at or datetime.now(UTC),
            artifact_id=artifact_id,
            session_id=session_id,
            input_tokens=spent.input_tokens,
            output_tokens=spent.output_tokens,
            cache_creation_tokens=spent.cache_creation_tokens,
            cache_read_tokens=spent.cache_read_tokens,
            total_tokens=spent.total_tokens,
            error_message=error_message,
            exit_code=exit_code,
        )
