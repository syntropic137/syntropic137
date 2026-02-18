"""Dispatch triggered workflow slice.

Subscribes to TriggerFired events and dispatches workflow executions.
"""

from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)

__all__ = ["WorkflowDispatchProjection"]
