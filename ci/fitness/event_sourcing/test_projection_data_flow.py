"""Fitness function: projection data-flow invariants (#513).

Verify that all coordinator projections can actually process events
without errors — each projection must declare subscriptions, have a
name, and carry a valid version.

These tests use no infrastructure — they import classes and inspect
structural properties only.
"""

from __future__ import annotations

import pytest
from ci.fitness.event_sourcing.test_projection_wiring import _get_coordinator_projections


@pytest.mark.architecture
class TestProjectionDataFlow:
    """Every coordinator projection must satisfy basic data-flow contracts."""

    def test_all_projections_have_non_empty_subscribed_event_types(self) -> None:
        """get_subscribed_event_types() must return a non-empty set.

        An empty or None subscription means the projection receives ALL
        events — a performance footgun that must be explicitly opted into.
        """
        projections = _get_coordinator_projections()
        for proj in projections:
            event_types = proj.get_subscribed_event_types()
            assert event_types is not None and len(event_types) > 0, (
                f"Projection '{proj.get_name()}' returns None or empty from "
                f"get_subscribed_event_types(). Declare explicit event subscriptions."
            )

    def test_all_projections_have_non_empty_name(self) -> None:
        """get_name() must return a non-empty string.

        Empty names cause checkpoint key collisions and make debugging
        impossible.
        """
        projections = _get_coordinator_projections()
        for proj in projections:
            name = proj.get_name()
            assert isinstance(name, str) and len(name.strip()) > 0, (
                f"Projection {type(proj).__name__} returns empty or non-string "
                f"from get_name(). Every projection needs a unique, non-empty name."
            )

    def test_all_projections_have_valid_version(self) -> None:
        """get_version() must return an int >= 1.

        Version 0 or negative indicates an uninitialized or invalid
        projection schema version. Versions start at 1 and increment
        when the projection schema changes (triggering a rebuild).
        """
        projections = _get_coordinator_projections()
        for proj in projections:
            version = proj.get_version()
            assert isinstance(version, int) and version >= 1, (
                f"Projection '{proj.get_name()}' returns invalid version "
                f"{version!r} from get_version(). Must be an int >= 1."
            )
