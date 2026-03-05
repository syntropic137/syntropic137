"""Position checkpoint for event subscription tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from syn_adapters.projection_stores import ProjectionStoreProtocol

logger = get_logger(__name__)


class PositionCheckpoint:
    """Manages subscription position persistence and consistency.

    Tracks the last processed event position and saves it to a projection store
    for crash recovery. Includes drift detection to catch scenarios where the
    projection store was reset while the event store wasn't.
    """

    def __init__(
        self,
        projection_store: ProjectionStoreProtocol,
        position_key: str,
    ) -> None:
        self._projection_store = projection_store
        self._position_key = position_key
        self._last_save_time: datetime | None = None

    @property
    def last_save_time(self) -> datetime | None:
        """Timestamp of the last successful position save."""
        return self._last_save_time

    async def load(self) -> int:
        """Load last processed position from projection store.

        Returns:
            Last saved position, or 0 if none found
        """
        try:
            position = await self._projection_store.get_position(self._position_key)
            if position is not None:
                logger.info(
                    "Loaded subscription position",
                    extra={"position": position},
                )
                return position
            else:
                logger.info("No previous subscription position found, starting from 0")
                return 0
        except Exception as e:
            logger.warning(
                "Failed to load subscription position, starting from 0",
                extra={"error": str(e)},
            )
            return 0

    async def save(self, position: int) -> None:
        """Save current position to projection store.

        Args:
            position: Current position to save
        """
        try:
            await self._projection_store.set_position(
                self._position_key,
                position,
            )
            self._last_save_time = datetime.now(UTC)
            logger.debug(
                "Saved subscription position",
                extra={"position": position},
            )
        except Exception as e:
            logger.error(
                "Failed to save subscription position",
                extra={"error": str(e), "position": position},
            )

    async def validate_consistency(self, position: int) -> None:
        """Validate that position is consistent with projection data.

        Detects position drift scenarios:
        1. Position saved but projection store was reset
        2. Position saved but projections failed to persist
        3. Event store and projection store using different backends

        Logs CRITICAL warning if drift detected but does NOT auto-reset.

        Args:
            position: Current position to validate
        """
        if position == 0:
            return

        try:
            executions = await self._projection_store.get_all("workflow_executions")
            sessions = await self._projection_store.get_all("agent_sessions")

            total_records = len(executions) + len(sessions)

            if total_records == 0 and position > 10:
                logger.critical(
                    "[SUBSCRIPTION] POSITION DRIFT DETECTED! "
                    "Saved position exists but projection data is empty. "
                    "This indicates the projection store was reset while event store wasn't. "
                    "Consider running 'just dev-fresh' to reset both stores, "
                    "or manually reset the subscription position to 0.",
                    extra={
                        "saved_position": position,
                        "workflow_executions_count": len(executions),
                        "agent_sessions_count": len(sessions),
                        "action_required": "Operator intervention needed",
                    },
                )
            elif total_records > 0:
                logger.info(
                    "[SUBSCRIPTION] Position consistency check passed",
                    extra={
                        "saved_position": position,
                        "workflow_executions_count": len(executions),
                        "agent_sessions_count": len(sessions),
                    },
                )
        except Exception as e:
            logger.warning(
                "[SUBSCRIPTION] Could not validate position consistency",
                extra={"error": str(e), "saved_position": position},
            )
