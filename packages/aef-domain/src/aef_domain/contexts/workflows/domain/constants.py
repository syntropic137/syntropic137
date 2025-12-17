"""Constants for workflow domain.

Centralizes all magic strings to prevent typos and enable refactoring.
"""

from typing import Final

# =============================================================================
# Phase Definition Fields
# =============================================================================


class PhaseFields:
    """Field names for phase definitions."""

    ID: Final[str] = "id"
    PHASE_ID: Final[str] = "phase_id"
    NAME: Final[str] = "name"
    DESCRIPTION: Final[str] = "description"
    AGENT_TYPE: Final[str] = "agent_type"
    ORDER: Final[str] = "order"
    PROMPT_TEMPLATE: Final[str] = "prompt_template"
    TIMEOUT_SECONDS: Final[str] = "timeout_seconds"
    ALLOWED_TOOLS: Final[str] = "allowed_tools"
    MAX_TOKENS: Final[str] = "max_tokens"
    OUTPUT_ARTIFACTS: Final[str] = "output_artifacts"
    INPUT_ARTIFACTS: Final[str] = "input_artifacts"


# =============================================================================
# Workflow Definition Fields
# =============================================================================


class WorkflowFields:
    """Field names for workflow definitions."""

    ID: Final[str] = "id"
    NAME: Final[str] = "name"
    WORKFLOW_TYPE: Final[str] = "workflow_type"
    CLASSIFICATION: Final[str] = "classification"
    DESCRIPTION: Final[str] = "description"
    PHASES: Final[str] = "phases"
    CREATED_AT: Final[str] = "created_at"
    RUNS_COUNT: Final[str] = "runs_count"
    REPOSITORY: Final[str] = "repository"


# =============================================================================
# Default Values
# =============================================================================


class PhaseDefaults:
    """Default values for phase definitions."""

    TIMEOUT_SECONDS: Final[int] = 300
    MAX_TOKENS: Final[int] = 16384
    AGENT_TYPE: Final[str] = ""
    ORDER: Final[int] = 0
