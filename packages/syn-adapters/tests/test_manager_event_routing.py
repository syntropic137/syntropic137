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
