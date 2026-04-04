"""Fitness function: projection wiring invariants.

Structural checks that catch projection misconfiguration at CI time:
- Coordinator has the expected number of projections
- No duplicate projection names (would cause checkpoint collisions)
- All projections declare explicit event subscriptions
- Trigger namespace constants match between writer and reader
- Every subscribed event type has a dispatch handler

These tests use no infrastructure — they import classes and inspect structure.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_coordinator_projections() -> list[object]:
    """Instantiate the coordinator's projection list without infrastructure.

    Uses object() as the store arg — constructors just store it,
    no validation occurs.
    """
    from syn_adapters.projections.trigger_query_projection import TriggerQueryProjection
    from syn_adapters.subscriptions.realtime_adapter import (
        OrganizationListAdapter,
        RepoListAdapter,
        SystemListAdapter,
    )
    from syn_domain.contexts.agent_sessions.slices.list_sessions import (
        SessionListProjection,
    )
    from syn_domain.contexts.artifacts.slices.list_artifacts import (
        ArtifactListProjection,
    )
    from syn_domain.contexts.github.slices.dispatch_triggered_workflow import (
        WorkflowDispatchProjection,
    )
    from syn_domain.contexts.orchestration.slices.dashboard_metrics import (
        DashboardMetricsProjection,
    )
    from syn_domain.contexts.orchestration.slices.get_execution_detail import (
        WorkflowExecutionDetailProjection,
    )
    from syn_domain.contexts.orchestration.slices.get_workflow_detail import (
        WorkflowDetailProjection,
    )
    from syn_domain.contexts.orchestration.slices.list_executions import (
        WorkflowExecutionListProjection,
    )
    from syn_domain.contexts.orchestration.slices.list_workflows import (
        WorkflowListProjection,
    )
    from syn_domain.contexts.organization._shared.organization_projection import (
        OrganizationProjection,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        RepoProjection,
    )
    from syn_domain.contexts.organization.slices.list_systems.projection import (
        SystemProjection,
    )

    dummy = object()
    return [
        WorkflowListProjection(dummy),
        WorkflowDetailProjection(dummy),
        WorkflowExecutionListProjection(dummy),
        WorkflowExecutionDetailProjection(dummy),
        SessionListProjection(dummy),
        ArtifactListProjection(dummy),
        DashboardMetricsProjection(dummy),
        WorkflowDispatchProjection(execution_service=None, store=dummy),
        TriggerQueryProjection(dummy),
        OrganizationListAdapter(OrganizationProjection(dummy)),
        SystemListAdapter(SystemProjection(dummy)),
        RepoListAdapter(RepoProjection(dummy)),
    ]


# Expected count — update when adding/removing projections from the coordinator.
# If this fails, you added or removed a projection. Update _EXPECTED_COUNT
# and the list in _get_coordinator_projections() above.
_EXPECTED_COUNT = 12


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.architecture
class TestProjectionWiring:
    """Structural invariants for the coordinator projection pipeline."""

    def test_coordinator_projection_count(self) -> None:
        """Projection list size must match canonical count.

        If you added a projection to create_coordinator_service(),
        add it to _get_coordinator_projections() above and bump _EXPECTED_COUNT.
        """
        projections = _get_coordinator_projections()
        assert len(projections) == _EXPECTED_COUNT, (
            f"Expected {_EXPECTED_COUNT} coordinator projections, got {len(projections)}. "
            f"Update _EXPECTED_COUNT and _get_coordinator_projections() in this test file."
        )

    def test_unique_projection_names(self) -> None:
        """No two projections may share the same name (checkpoint collision)."""
        projections = _get_coordinator_projections()
        names = [p.get_name() for p in projections]
        duplicates = [n for n in names if names.count(n) > 1]
        assert not duplicates, (
            f"Duplicate projection names would cause checkpoint collisions: "
            f"{set(duplicates)}"
        )

    def test_all_projections_declare_event_subscriptions(self) -> None:
        """Every projection must return a non-empty set from get_subscribed_event_types().

        Returning None means 'subscribe to ALL events' — a performance footgun
        that should be explicitly allowlisted.
        """
        projections = _get_coordinator_projections()
        for proj in projections:
            event_types = proj.get_subscribed_event_types()
            assert event_types is not None and len(event_types) > 0, (
                f"Projection '{proj.get_name()}' returns None or empty from "
                f"get_subscribed_event_types(). Declare explicit event subscriptions."
            )


@pytest.mark.architecture
class TestTriggerNamespaceAlignment:
    """Namespace constants must match between projection (writer) and store (reader)."""

    def test_trigger_index_namespace(self) -> None:
        from syn_adapters.projections.trigger_query_projection import (
            NS_TRIGGER_INDEX as PROJ_NS,
        )
        from syn_adapters.storage.trigger_query_store import (
            NS_TRIGGER_INDEX as STORE_NS,
        )

        assert PROJ_NS == STORE_NS, (
            f"trigger_index namespace mismatch: projection writes to '{PROJ_NS}' "
            f"but store reads from '{STORE_NS}'"
        )

    def test_fire_records_namespace(self) -> None:
        from syn_adapters.projections.trigger_query_projection import (
            NS_FIRE_RECORDS as PROJ_NS,
        )
        from syn_adapters.storage.trigger_query_store import (
            NS_FIRE_RECORDS as STORE_NS,
        )

        assert PROJ_NS == STORE_NS, (
            f"trigger_fire_records namespace mismatch: projection writes to '{PROJ_NS}' "
            f"but store reads from '{STORE_NS}'"
        )

    def test_deliveries_namespace(self) -> None:
        from syn_adapters.projections.trigger_query_projection import (
            NS_DELIVERIES as PROJ_NS,
        )
        from syn_adapters.storage.trigger_query_store import (
            NS_DELIVERIES as STORE_NS,
        )

        assert PROJ_NS == STORE_NS, (
            f"trigger_deliveries namespace mismatch: projection writes to '{PROJ_NS}' "
            f"but store reads from '{STORE_NS}'"
        )


@pytest.mark.architecture
class TestEventHandlerCoverage:
    """Every subscribed event type must have a dispatch handler."""

    def test_trigger_projection_handlers_cover_all_events(self) -> None:
        """TriggerQueryProjection must handle every event it subscribes to."""
        from syn_adapters.projections.trigger_query_projection import (
            TriggerQueryProjection,
            _SUBSCRIBED_EVENTS,
        )

        dispatch_map = TriggerQueryProjection._EVENT_DISPATCH
        # TriggerFired is special-cased in _dispatch_event, not in _EVENT_DISPATCH
        handled = set(dispatch_map.keys()) | {"github.TriggerFired"}
        missing = _SUBSCRIBED_EVENTS - handled
        assert not missing, (
            f"TriggerQueryProjection subscribes to events with no handler: {missing}"
        )

    def test_no_orphaned_dispatch_entries(self) -> None:
        """_EVENT_DISPATCH must not contain events that aren't subscribed to."""
        from syn_adapters.projections.trigger_query_projection import (
            TriggerQueryProjection,
            _SUBSCRIBED_EVENTS,
        )

        dispatch_map = TriggerQueryProjection._EVENT_DISPATCH
        orphaned = set(dispatch_map.keys()) - _SUBSCRIBED_EVENTS
        assert not orphaned, (
            f"TriggerQueryProjection has dispatch entries for unsubscribed events: {orphaned}"
        )
