"""Read model for workflow TEMPLATE detail views.

NOTE: This is for workflow TEMPLATES (definitions), not executions.
Templates don't have status, started_at, completed_at, etc.
For execution details, see WorkflowExecutionDetail.
"""

from dataclasses import dataclass, field
from datetime import datetime

from syn_domain.contexts.orchestration.domain.constants import (
    PhaseDefaults,
    PhaseFields,
    WorkflowFields,
)


@dataclass(frozen=True)
class PhaseDefinitionDetail:
    """Read model for phase DEFINITION within a workflow template.

    This represents the phase as defined in the template,
    NOT the execution state of a phase.
    """

    id: str
    """Phase identifier."""

    name: str
    """Display name of the phase."""

    description: str | None = None
    """Optional description of what this phase does."""

    agent_type: str = PhaseDefaults.AGENT_TYPE
    """Type of agent to use for this phase."""

    order: int = PhaseDefaults.ORDER
    """Order in which this phase executes."""

    prompt_template: str | None = None
    """The prompt template for this phase (required for agent execution)."""

    timeout_seconds: int = PhaseDefaults.TIMEOUT_SECONDS
    """Timeout for phase execution in seconds."""

    allowed_tools: tuple[str, ...] = ()
    """Tools allowed during this phase execution."""

    argument_hint: str | None = None
    """Hint for what $ARGUMENTS expects (e.g., '[task-description]')."""

    model: str | None = None
    """Per-phase model override (e.g., 'sonnet', 'opus')."""


@dataclass(frozen=True)
class InputDeclarationDetail:
    """Read model for an input declaration within a workflow template."""

    name: str
    description: str | None = None
    required: bool = True
    default: str | None = None


@dataclass(frozen=True)
class WorkflowDetail:
    """Read model for workflow TEMPLATE detail view.

    This represents a workflow definition/template.
    Templates are reusable definitions that can be executed multiple times.
    Each execution creates a WorkflowExecution with its own status and metrics.
    """

    id: str
    """Unique identifier for the workflow template."""

    name: str
    """Display name of the workflow."""

    workflow_type: str
    """Type of workflow (e.g., 'research', 'implementation')."""

    classification: str
    """Classification category of the workflow."""

    description: str | None
    """Optional description of the workflow."""

    phases: list[PhaseDefinitionDetail] = field(default_factory=list)
    """List of phase definitions in the workflow."""

    input_declarations: list[InputDeclarationDetail] = field(default_factory=list)
    """Declared inputs for this workflow (ISS-211)."""

    created_at: datetime | None = None
    """When the workflow template was created."""

    runs_count: int = 0
    """Number of times this workflow has been executed."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowDetail":
        """Create from dictionary data."""
        phases_data = data.get(WorkflowFields.PHASES, [])
        phases = [
            PhaseDefinitionDetail(
                id=p.get(PhaseFields.ID, p.get(PhaseFields.PHASE_ID, "")),
                name=p.get(PhaseFields.NAME, ""),
                description=p.get(PhaseFields.DESCRIPTION),
                agent_type=p.get(PhaseFields.AGENT_TYPE, PhaseDefaults.AGENT_TYPE),
                order=p.get(PhaseFields.ORDER, i),
                prompt_template=p.get(PhaseFields.PROMPT_TEMPLATE),
                timeout_seconds=p.get(PhaseFields.TIMEOUT_SECONDS, PhaseDefaults.TIMEOUT_SECONDS),
                allowed_tools=tuple(p.get(PhaseFields.ALLOWED_TOOLS, [])),
                argument_hint=p.get("argument_hint"),
                model=p.get("model"),
            )
            for i, p in enumerate(phases_data)
        ]

        input_decls_data = data.get("input_declarations", [])
        input_decls = [
            InputDeclarationDetail(
                name=d.get("name", ""),
                description=d.get("description"),
                required=d.get("required", True),
                default=d.get("default"),
            )
            for d in input_decls_data
        ]

        return cls(
            id=data[WorkflowFields.ID],
            name=data[WorkflowFields.NAME],
            workflow_type=data.get(WorkflowFields.WORKFLOW_TYPE, ""),
            classification=data.get(WorkflowFields.CLASSIFICATION, ""),
            description=data.get(WorkflowFields.DESCRIPTION),
            phases=phases,
            input_declarations=input_decls,
            created_at=data.get(WorkflowFields.CREATED_AT),
            runs_count=data.get(WorkflowFields.RUNS_COUNT, 0),
        )

    @staticmethod
    def _to_iso_string(value: datetime | str | None) -> str | None:
        """Convert datetime or string to ISO string."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return value.isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""

        def phase_to_dict(p: PhaseDefinitionDetail | dict) -> dict:
            """Convert a phase to dict."""
            if isinstance(p, dict):
                return p
            return {
                PhaseFields.ID: p.id,
                PhaseFields.NAME: p.name,
                PhaseFields.DESCRIPTION: p.description,
                PhaseFields.AGENT_TYPE: p.agent_type,
                PhaseFields.ORDER: p.order,
                PhaseFields.PROMPT_TEMPLATE: p.prompt_template,
                PhaseFields.TIMEOUT_SECONDS: p.timeout_seconds,
                PhaseFields.ALLOWED_TOOLS: list(p.allowed_tools),
                "argument_hint": p.argument_hint,
                "model": p.model,
            }

        def input_decl_to_dict(d: InputDeclarationDetail | dict) -> dict:
            if isinstance(d, dict):
                return d
            return {
                "name": d.name,
                "description": d.description,
                "required": d.required,
                "default": d.default,
            }

        return {
            WorkflowFields.ID: self.id,
            WorkflowFields.NAME: self.name,
            WorkflowFields.WORKFLOW_TYPE: self.workflow_type,
            WorkflowFields.CLASSIFICATION: self.classification,
            WorkflowFields.DESCRIPTION: self.description,
            WorkflowFields.PHASES: [phase_to_dict(p) for p in self.phases],
            "input_declarations": [input_decl_to_dict(d) for d in self.input_declarations],
            WorkflowFields.CREATED_AT: self._to_iso_string(self.created_at),
            WorkflowFields.RUNS_COUNT: self.runs_count,
        }
