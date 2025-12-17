"""Pydantic models for parsing workflow YAML definitions.

These models define the schema for workflow YAML files and provide
validation when loading workflow definitions from disk.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - needed at runtime for file operations

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aef_domain.contexts.workflows._shared.value_objects import (
    PhaseDefinition,
    PhaseExecutionType,
    WorkflowClassification,
    WorkflowType,
)


class RepositoryConfig(BaseModel):
    """Repository configuration for a workflow."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(..., min_length=1)
    ref: str = Field(default="main")


class PhaseYamlDefinition(BaseModel):
    """Phase definition as parsed from YAML.

    Converts YAML snake_case to domain PhaseDefinition.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., alias="id", min_length=1)
    name: str = Field(..., min_length=1, max_length=255)
    order: int = Field(..., ge=1)
    execution_type: PhaseExecutionType = PhaseExecutionType.SEQUENTIAL
    description: str | None = None

    # YAML uses different names than domain model
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)

    # Agent configuration
    prompt_template: str | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None

    def to_domain(self) -> PhaseDefinition:
        """Convert to domain PhaseDefinition."""
        return PhaseDefinition(
            phase_id=self.id,
            name=self.name,
            order=self.order,
            execution_type=self.execution_type,
            description=self.description,
            input_artifact_types=self.input_artifacts,
            output_artifact_types=self.output_artifacts,
            prompt_template=self.prompt_template,
            max_tokens=self.max_tokens,
            timeout_seconds=self.timeout_seconds,
        )


class WorkflowDefinition(BaseModel):
    """Complete workflow definition as parsed from YAML.

    This is the root model for workflow YAML files.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

    # Classification
    type: WorkflowType = WorkflowType.CUSTOM
    classification: WorkflowClassification = WorkflowClassification.STANDARD

    # Repository context
    repository: RepositoryConfig | None = None

    # Project association
    project_name: str | None = None

    # Phases
    phases: list[PhaseYamlDefinition] = Field(..., min_length=1)

    @field_validator("phases")
    @classmethod
    def validate_phase_order(cls, phases: list[PhaseYamlDefinition]) -> list[PhaseYamlDefinition]:
        """Ensure phases have unique IDs and sequential order."""
        phase_ids = [p.id for p in phases]
        if len(phase_ids) != len(set(phase_ids)):
            msg = "Phase IDs must be unique within a workflow"
            raise ValueError(msg)

        orders = [p.order for p in phases]
        if len(orders) != len(set(orders)):
            msg = "Phase orders must be unique within a workflow"
            raise ValueError(msg)

        return phases

    @classmethod
    def from_yaml(cls, content: str) -> WorkflowDefinition:
        """Parse workflow definition from YAML string."""
        data = yaml.safe_load(content)
        return cls.model_validate(data)

    @classmethod
    def from_file(cls, path: Path) -> WorkflowDefinition:
        """Load workflow definition from a YAML file."""
        content = path.read_text(encoding="utf-8")
        return cls.from_yaml(content)

    def get_domain_phases(self) -> list[PhaseDefinition]:
        """Convert all phases to domain PhaseDefinition objects."""
        return [p.to_domain() for p in self.phases]


def load_workflow_definitions(directory: Path) -> list[WorkflowDefinition]:
    """Load all workflow definitions from a directory.

    Args:
        directory: Path to directory containing YAML files.

    Returns:
        List of parsed WorkflowDefinition objects.

    Raises:
        FileNotFoundError: If directory doesn't exist.
        ValueError: If any YAML file is invalid.
    """
    if not directory.exists():
        msg = f"Workflow directory does not exist: {directory}"
        raise FileNotFoundError(msg)

    definitions: list[WorkflowDefinition] = []
    yaml_files = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))

    for yaml_file in yaml_files:
        definition = WorkflowDefinition.from_file(yaml_file)
        definitions.append(definition)

    return definitions


def validate_workflow_yaml(content: str) -> tuple[bool, str | None]:
    """Validate workflow YAML content without loading.

    Args:
        content: YAML content to validate.

    Returns:
        Tuple of (is_valid, error_message).
    """
    try:
        WorkflowDefinition.from_yaml(content)
        return (True, None)
    except Exception as e:
        return (False, str(e))
