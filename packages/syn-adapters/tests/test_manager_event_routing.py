"""Tests for ProjectionManager event routing completeness.

Guards against the class of bug where a new event type is added (or a new
projection created) but the wiring in manager.py is never updated, causing
events to be silently dropped and projections to stay empty.

Companion to test_projection_dispatch_coverage.py in syn-domain.
"""

import pytest


@pytest.mark.unit
def test_all_event_handler_projection_keys_are_registered():
    """Every projection key referenced in EVENT_HANDLERS must be registered.

    Catches: adding an event to EVENT_HANDLERS pointing at a projection name
    that was never added to _projections, causing silent dispatch failure.
    """
    import os

    os.environ.setdefault("APP_ENVIRONMENT", "test")

    from syn_adapters.projections.manager import EVENT_HANDLERS, ProjectionManager

    manager = ProjectionManager()
    manager._ensure_initialized()
    registered = set(manager._projections.keys())

    failures = []
    for event_type, handlers in EVENT_HANDLERS.items():
        for proj_name, method_name in handlers:
            if proj_name not in registered:
                failures.append(
                    f"EVENT_HANDLERS['{event_type}'] → '{proj_name}.{method_name}' "
                    f"but '{proj_name}' is not in _projections"
                )

    assert not failures, (
        "EVENT_HANDLERS references projection keys not registered in _projections:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


@pytest.mark.unit
def test_org_event_handler_methods_exist():
    """Every method referenced in EVENT_HANDLERS for org events must exist.

    Scoped to the organization context events added in ISS-225/ISS-262 fix.
    Catches typos like 'on_org_created' vs 'on_organization_created'.
    """
    import os

    os.environ.setdefault("APP_ENVIRONMENT", "test")

    from syn_adapters.projections.manager import EVENT_HANDLERS, ProjectionManager

    org_event_types = {
        "organization.OrganizationCreated",
        "organization.OrganizationUpdated",
        "organization.OrganizationDeleted",
        "organization.SystemCreated",
        "organization.SystemUpdated",
        "organization.SystemDeleted",
        "organization.RepoRegistered",
        "organization.RepoAssignedToSystem",
        "organization.RepoUnassignedFromSystem",
    }

    manager = ProjectionManager()
    manager._ensure_initialized()

    failures = []
    for event_type in org_event_types:
        for proj_name, method_name in EVENT_HANDLERS.get(event_type, []):
            projection = manager._projections.get(proj_name)
            if projection is None:
                continue  # caught by previous test
            if not hasattr(projection, method_name):
                failures.append(
                    f"EVENT_HANDLERS['{event_type}'] → '{proj_name}.{method_name}' "
                    f"but method '{method_name}' does not exist on {type(projection).__name__}"
                )

    assert not failures, (
        "Org EVENT_HANDLERS references methods that do not exist on projections:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


@pytest.mark.unit
@pytest.mark.xfail(
    reason="TODO(#444): 6 EVENT_HANDLERS entries reference methods that don't exist yet "
    "(ExecutionPaused, ExecutionResumed, CostRecorded). These events are silently dropped.",
    strict=True,
)
def test_all_handler_methods_exist_on_projections():
    """Every method referenced in EVENT_HANDLERS must exist on its projection.

    Catches: typos in method names like 'on_workflow_create' vs 'on_workflow_created',
    or methods that were renamed/removed but not updated in EVENT_HANDLERS.
    """
    import os

    os.environ.setdefault("APP_ENVIRONMENT", "test")

    from syn_adapters.projections.manager import EVENT_HANDLERS, ProjectionManager

    manager = ProjectionManager()
    manager._ensure_initialized()

    failures = []
    for event_type, handlers in EVENT_HANDLERS.items():
        for proj_name, method_name in handlers:
            projection = manager._projections.get(proj_name)
            if projection is None:
                continue  # caught by test_all_event_handler_projection_keys_are_registered
            if not hasattr(projection, method_name):
                failures.append(
                    f"EVENT_HANDLERS['{event_type}'] → '{proj_name}.{method_name}' "
                    f"but method '{method_name}' does not exist on {type(projection).__name__}"
                )

    assert not failures, (
        "EVENT_HANDLERS references methods that do not exist on projections:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


@pytest.mark.unit
@pytest.mark.xfail(
    reason="TODO(#444): 5 orphaned on_* handlers exist but are not wired in EVENT_HANDLERS "
    "(WorkflowPhaseUpdated, WorkflowInterrupted, PhaseStarted). These handlers are never called.",
    strict=True,
)
def test_no_orphaned_on_handlers():
    """Every on_* handler on registered projections should be wired in EVENT_HANDLERS.

    Catches: adding on_new_event_type() to a projection but forgetting to register
    it in EVENT_HANDLERS, causing the handler to exist but never be called.

    Some projections are wrapped in _NamespacedProjectionAdapter (e.g. organization
    context) — the adapter handles routing, so the inner projection's on_* methods
    are correctly called even though they don't appear directly in EVENT_HANDLERS.
    These are excluded.
    """
    import os

    os.environ.setdefault("APP_ENVIRONMENT", "test")

    from syn_adapters.projections.manager import EVENT_HANDLERS, ProjectionManager

    manager = ProjectionManager()
    manager._ensure_initialized()

    # Build reverse lookup: (proj_name, method_name) → event_type
    wired: set[tuple[str, str]] = set()
    for _event_type, handlers in EVENT_HANDLERS.items():
        for proj_name, method_name in handlers:
            wired.add((proj_name, method_name))

    # Projections routed through _NamespacedProjectionAdapter — their on_*
    # methods are called by the adapter's handle_event, not EVENT_HANDLERS.
    adapter_routed_projections = {"organization_list", "system_list", "repo_list"}

    # Check all registered projections for orphaned on_* methods
    failures = []
    for proj_name, projection in manager._projections.items():
        if proj_name in adapter_routed_projections:
            continue  # Routed via _NamespacedProjectionAdapter

        for attr_name in dir(projection):
            if not attr_name.startswith("on_") or attr_name.startswith("on__"):
                continue
            if not callable(getattr(projection, attr_name, None)):
                continue
            # Skip methods from base classes (ABC, Protocol)
            if attr_name in ("on_event",):
                continue
            if (proj_name, attr_name) not in wired:
                failures.append(
                    f"'{proj_name}.{attr_name}' exists but is not wired in EVENT_HANDLERS"
                )

    assert not failures, (
        "Projection handlers exist but are not wired in EVENT_HANDLERS (orphaned):\n"
        + "\n".join(f"  - {f}" for f in failures)
        + "\n\nIf a handler is intentionally not in EVENT_HANDLERS "
        "(e.g. called from another handler), add it to the exclusion list in this test."
    )


@pytest.mark.unit
def test_organization_events_are_routed():
    """Organization context events must all be in EVENT_HANDLERS.

    Regression guard: these events were previously missing, causing
    org/system/repo creates to succeed but never appear in list/show.
    """
    from syn_adapters.projections.manager import EVENT_HANDLERS

    required = {
        "organization.OrganizationCreated",
        "organization.OrganizationUpdated",
        "organization.OrganizationDeleted",
        "organization.SystemCreated",
        "organization.SystemUpdated",
        "organization.SystemDeleted",
        "organization.RepoRegistered",
        "organization.RepoAssignedToSystem",
        "organization.RepoUnassignedFromSystem",
    }
    missing = required - set(EVENT_HANDLERS.keys())
    assert not missing, (
        f"Organization context events missing from EVENT_HANDLERS: {missing}\n"
        "This causes creates to succeed but data to never appear in list/show."
    )
