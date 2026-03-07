"""Repo-execution correlation slice.

Maps repositories to workflow executions using TriggerFired
and WorkflowExecutionStarted events.
"""

from .projection import RepoCorrelationProjection

__all__ = ["RepoCorrelationProjection"]
