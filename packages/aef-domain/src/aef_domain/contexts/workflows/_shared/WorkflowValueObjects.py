"""Value objects for the workflows bounded context."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class WorkflowType(str, Enum):
    """Type of workflow execution."""

    RESEARCH = "research"
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    DEPLOYMENT = "deployment"
    CUSTOM = "custom"


class WorkflowClassification(str, Enum):
    """Classification of workflow complexity."""

    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"
    EPIC = "epic"


class PhaseExecutionType(str, Enum):
    """How a phase should be executed."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HUMAN_IN_LOOP = "human_in_loop"


class PhaseDefinition(BaseModel):
    """Definition of a workflow phase.

    Phases are the building blocks of workflows.
    Each phase has inputs, outputs, and execution parameters.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    phase_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255)
    order: int = Field(..., ge=1)

    # Execution
    execution_type: PhaseExecutionType = PhaseExecutionType.SEQUENTIAL

    # Description
    description: str | None = None

    # Input/Output definitions
    input_artifact_types: list[str] = Field(default_factory=list)
    output_artifact_types: list[str] = Field(default_factory=list)

    # Agent configuration
    prompt_template: str | None = None
    """The actual prompt template content for this phase."""

    max_tokens: int | None = None
    timeout_seconds: int | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    """Tools allowed during this phase execution."""
