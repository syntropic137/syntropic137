"""Projection store collection names for the organization context."""

# Correlation tracking
REPO_CORRELATION = "repo_correlation"

# Per-repo insight projections
REPO_COST = "repo_cost"
REPO_HEALTH = "repo_health"
REPO_ACTIVITY = "repo_activity"
REPO_FAILURE = "repo_failure"

# Cross-context projections (owned by other contexts)
SESSION_SUMMARIES = "session_summaries"
WORKFLOW_EXECUTIONS = "workflow_executions"  # owned by orchestration/slices/list_executions
