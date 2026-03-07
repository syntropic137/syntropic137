"""CI safety test for projection dispatch coverage.

Prevents the class of bug where a new event type is added to
_SUBSCRIBED_EVENTS but the corresponding dispatch branch is forgotten
(or vice versa), which silently corrupts read model data.

Two guards:

1. AutoDispatchProjection subclasses — naming convention check:
   Every public on_* method name must correctly round-trip through
   camel_to_snake(snake_to_camel(suffix)), ensuring the method name maps
   unambiguously to a CamelCase event type.

2. CheckpointedProjection with manual dispatch — dispatch completeness check:
   Every event type in _SUBSCRIBED_EVENTS must appear as a quoted string
   literal in the handle_event source, catching the original bug class.
"""

import inspect
import re

import pytest
from event_sourcing import AutoDispatchProjection, CheckpointedProjection
from event_sourcing.core.checkpoint import _snake_to_camel

import syn_domain.contexts.agent_sessions.slices.list_sessions.projection
import syn_domain.contexts.artifacts.slices.list_artifacts.projection
import syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection
import syn_domain.contexts.github.slices.list_triggers.projection
import syn_domain.contexts.orchestration.slices.dashboard_metrics.projection
import syn_domain.contexts.orchestration.slices.get_execution_detail.projection
import syn_domain.contexts.orchestration.slices.get_workflow_detail.projection
import syn_domain.contexts.orchestration.slices.list_executions.projection
import syn_domain.contexts.orchestration.slices.list_workflows.projection
import syn_domain.contexts.orchestration.slices.workflow_phase_metrics.projection
import syn_domain.contexts.orchestration.slices.workspace_metrics.projection
import syn_domain.contexts.organization.slices.repo_correlation.projection
import syn_domain.contexts.organization.slices.repo_cost.projection
import syn_domain.contexts.organization.slices.repo_health.projection  # noqa: F401


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case (test-only helper for round-trip checks)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _all_subclasses(cls: type) -> list[type]:
    """Recursively collect all concrete subclasses."""
    result = []
    for sub in cls.__subclasses__():
        if not inspect.isabstract(sub):
            result.append(sub)
        result.extend(_all_subclasses(sub))
    return result


def _public_on_methods(cls: type) -> list[str]:
    """Return names of all public on_* methods defined on cls (any MRO level)."""
    seen: set[str] = set()
    names = []
    for klass in cls.__mro__:
        for attr, value in vars(klass).items():
            if (
                attr.startswith("on_")
                and not attr.startswith("on__")
                and callable(value)
                and attr not in seen
            ):
                seen.add(attr)
                names.append(attr)
    return names


@pytest.mark.unit
class TestAutoDispatchProjectionNamingConvention:
    """Guard: on_* method names in AutoDispatchProjection subclasses must
    be derivable from a valid CamelCase event type via camel_to_snake."""

    def test_all_on_methods_round_trip(self):
        """Every on_<suffix> method name must satisfy:
        camel_to_snake(snake_to_camel(suffix)) == suffix

        This ensures the suffix is a valid, unambiguous snake_case name
        that can be derived from a CamelCase event type.
        """
        auto_dispatch_classes = _all_subclasses(AutoDispatchProjection)
        assert auto_dispatch_classes, (
            "No AutoDispatchProjection subclasses found — imports may have failed"
        )

        failures = []
        for cls in auto_dispatch_classes:
            for method_name in _public_on_methods(cls):
                suffix = method_name[3:]  # strip "on_"
                camel = _snake_to_camel(suffix)
                round_tripped = _camel_to_snake(camel)
                if round_tripped != suffix:
                    failures.append(
                        f"{cls.__name__}.{method_name}: "
                        f"suffix '{suffix}' -> CamelCase '{camel}' -> snake '{round_tripped}' "
                        f"(expected '{suffix}')"
                    )

        assert not failures, "Projection handler names fail round-trip check:\n" + "\n".join(
            f"  - {f}" for f in failures
        )


@pytest.mark.unit
class TestManualDispatchProjectionCoverage:
    """Guard: for CheckpointedProjection subclasses using manual dispatch,
    every event type in _SUBSCRIBED_EVENTS must appear as a quoted string
    in handle_event source."""

    def test_subscribed_events_are_dispatched(self):
        """Every event type in _SUBSCRIBED_EVENTS must appear quoted in handle_event.

        Catches: adding 'NewEvent' to _SUBSCRIBED_EVENTS but forgetting
        the elif branch in handle_event.
        """
        # Collect manual-dispatch projections (have _SUBSCRIBED_EVENTS defined on the class)
        all_checkpointed = _all_subclasses(CheckpointedProjection)
        manual_dispatch = [
            cls
            for cls in all_checkpointed
            if not issubclass(cls, AutoDispatchProjection) and hasattr(cls, "_SUBSCRIBED_EVENTS")
        ]

        failures = []
        for cls in manual_dispatch:
            subscribed = cls._SUBSCRIBED_EVENTS  # type: ignore[attr-defined]
            try:
                handle_event_src = inspect.getsource(cls.handle_event)
            except (TypeError, OSError):
                failures.append(f"{cls.__name__}: could not inspect handle_event source")
                continue

            for event_type in subscribed:
                if f'"{event_type}"' not in handle_event_src:
                    failures.append(
                        f"{cls.__name__}: '{event_type}' in _SUBSCRIBED_EVENTS "
                        f"but not found as quoted string in handle_event"
                    )

        assert not failures, (
            "Manual-dispatch projections have subscription/dispatch mismatch:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )
