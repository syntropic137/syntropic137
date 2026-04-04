"""Fitness function: projection registry completeness.

Ensures that projections defined in the manager registry are also
registered in the coordinator service. Prevents the split-brain
regression where projections exist but never receive events.

Refs: #504, #512
"""

from __future__ import annotations

import pytest

# Known exceptions — projections that intentionally stay out of the coordinator
_COORDINATOR_EXCEPTIONS = {
    "session_tools",  # Read-only TimescaleDB query interface, no event consumption
    "realtime",  # Added dynamically by CoordinatorSubscriptionService.start()
}

# Manager registry uses legacy names; coordinator projections use get_name().
# This mapping bridges the two so the completeness check works correctly.
# When the legacy ProjectionManager is retired, this mapping can be removed.
_MANAGER_TO_COORDINATOR_NAME: dict[str, str] = {
    "workflow_list": "workflow_summaries",
    "workflow_detail": "workflow_details",
    "workflow_execution_list": "workflow_executions",
    "workflow_execution_detail": "workflow_execution_details",
    "session_list": "session_summaries",
    "artifact_list": "artifact_summaries",
}


@pytest.mark.architecture
class TestProjectionRegistryCompleteness:
    """Every manager-registry projection must be in the coordinator (or explicitly excluded)."""

    def test_no_unregistered_projections(self) -> None:
        """Manager registry projections must have coordinator coverage.

        If this test fails, either:
        1. Add the projection to create_coordinator_service() in coordinator_service.py
        2. Add it to _COORDINATOR_EXCEPTIONS above with a comment explaining why
        """
        from syn_adapters.projections.manager_registry import build_projection_registry

        dummy = object()
        manager_projections = set(build_projection_registry(dummy).keys())

        # Get coordinator projection names
        from ci.fitness.event_sourcing.test_projection_wiring import (
            _get_coordinator_projections,
        )

        coordinator_names = {p.get_name() for p in _get_coordinator_projections()}

        # Normalize manager names to coordinator names using the mapping
        normalized_manager = {
            _MANAGER_TO_COORDINATOR_NAME.get(name, name) for name in manager_projections
        }

        # Find projections in manager but not in coordinator
        missing = normalized_manager - coordinator_names - _COORDINATOR_EXCEPTIONS

        assert not missing, (
            f"Projections in manager registry but NOT in coordinator: {missing}. "
            f"Add them to create_coordinator_service() in coordinator_service.py, "
            f"or add to _COORDINATOR_EXCEPTIONS in this test with justification."
        )
