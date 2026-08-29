"""Pydantic models for parsing workflow YAML definitions.

These models define the schema for workflow YAML files and provide
validation when loading workflow definitions from disk. Phases may
specify a ``prompt_file`` referencing an external ``.md`` file instead
of an inline ``prompt_template``. The ``.md`` file is loaded via
:func:`~syn_domain.contexts.orchestration._shared.md_prompt_loader.load_md_prompt`
and its frontmatter is merged into the phase definition at load time.

Phases can also reference shared prompts from a phase library using
the ``shared://`` prefix (e.g. ``prompt_file: shared://create-pr``),
which resolves to ``phase-library/create-pr.md`` relative to the
package root.  Content is resolved at load/install time (copy-on-create
semantics) — no runtime coupling to the library.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (
    ClaudePluginRef,  # noqa: TC001 - needed at runtime for Pydantic field validation
)
from syn_domain.contexts.orchestration._shared.md_prompt_loader import (
    load_md_prompt,
    normalize_frontmatter,
)
from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillRef,
    expand_skill_entry,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    InputDeclaration,
    PhaseDefinition,
    PhaseExecutionType,
    WorkflowClassification,
)
from syn_shared.agents import REMOVED_INTERACTIVE_PROVIDER, AgentProvider

_SHARED_PREFIX = "shared://"


def _resolve_shared_prompt_path(
    phase_id: str,
    prompt_file: str,
    phase_library_dir: Path | None,
) -> Path:
    """Resolve a ``shared://`` prompt reference to a filesystem path.

    Raises:
        ValueError: If no library dir is provided, reference is empty,
            or the resolved path escapes the library directory.
    """
    if phase_library_dir is None:
        msg = (
            f"Phase '{phase_id}': shared:// reference "
            f"'{prompt_file}' requires a phase-library directory"
        )
        raise ValueError(msg)

    ref_name = prompt_file.removeprefix(_SHARED_PREFIX)
    if not ref_name:
        msg = f"Phase '{phase_id}': shared:// reference is empty"
        raise ValueError(msg)

    prompt_path = phase_library_dir / f"{ref_name}.md"
    resolved = prompt_path.resolve()
    lib_resolved = phase_library_dir.resolve()
    if lib_resolved not in resolved.parents and resolved != lib_resolved:
        msg = f"Phase '{phase_id}': shared:// path '{ref_name}' escapes phase-library directory"
        raise ValueError(msg)

    return resolved


def _resolve_local_prompt_path(prompt_file: str, base_dir: Path) -> Path:
    """Resolve a relative prompt_file path with traversal security.

    Raises:
        ValueError: If the path is absolute or escapes the base directory.
    """
    prompt_path = Path(prompt_file)
    if prompt_path.is_absolute():
        msg = f"prompt_file must be a relative path, got: {prompt_file!r}"
        raise ValueError(msg)

    resolved = (base_dir / prompt_path).resolve()
    base_resolved = base_dir.resolve()
    if base_resolved not in resolved.parents and resolved != base_resolved:
        msg = f"prompt_file path {prompt_file!r} escapes base directory {str(base_resolved)!r}"
        raise ValueError(msg)

    return resolved


def _resolve_phase_prompt_file(
    phase: dict[str, Any],
    base_dir: Path,
    *,
    phase_library_dir: Path | None = None,
) -> None:
    """Resolve a single phase's prompt_file reference in-place.

    Loads the .md file, sets prompt_template to its body,
    merges normalized frontmatter (YAML values take precedence),
    and removes the prompt_file key.

    Supports ``shared://`` prefix for phase-library references.
    """
    if "prompt_template" in phase and phase["prompt_template"] is not None:
        msg = (
            f"Phase '{phase.get('id', '?')}': specify either "
            "'prompt_template' or 'prompt_file', not both"
        )
        raise ValueError(msg)

    prompt_file: str = phase["prompt_file"]
    phase_id = str(phase.get("id", "?"))

    if prompt_file.startswith(_SHARED_PREFIX):
        resolved = _resolve_shared_prompt_path(phase_id, prompt_file, phase_library_dir)
    else:
        resolved = _resolve_local_prompt_path(prompt_file, base_dir)

    md_prompt = load_md_prompt(resolved)

    # Merge frontmatter — YAML phase values take precedence.
    normalized = normalize_frontmatter(md_prompt.metadata)
    for key, value in normalized.items():
        if key not in phase or phase[key] is None:
            phase[key] = value

    phase["prompt_template"] = md_prompt.content
    del phase["prompt_file"]


class RepositoryConfig(BaseModel):
    """Repository configuration for a workflow."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(..., min_length=1)
    ref: str = Field(default="main")


class InputYamlDefinition(BaseModel):
    """Input declaration as parsed from YAML.

    Maps to domain InputDeclaration.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    description: str | None = None
    required: bool = True
    default: str | None = None

    def to_domain(self) -> InputDeclaration:
        """Convert to domain InputDeclaration."""
        return InputDeclaration(
            name=self.name,
            description=self.description,
            required=self.required,
            default=self.default,
        )


class AgentYamlDefinition(BaseModel):
    """Per-phase ``agent`` block as parsed from YAML.

    Selects which headless agent provider drives the phase (``claude`` for
    the default ``claude -p`` docker-exec path, ``codex`` for the
    programmatic ``codex exec`` harness on the same path) and optionally
    the model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["claude", "codex"] | None = None
    """One of: ``claude`` (default; ``claude -p`` path), ``codex``
    (programmatic ``codex exec`` harness on the same docker path).

    A ``Literal`` so the exported JSON schema keeps the enum. The REMOVED
    ``claude-interactive`` value is intercepted BEFORE this type check by
    ``_reject_removed_provider`` so a stale workflow gets a message naming
    the removal rather than a bare "Input should be 'claude' or 'codex'"."""

    model: str | None = None
    """Per-phase model override (e.g. ``sonnet``, ``opus``)."""

    allow_delegation: bool = False
    """When true, stage BOTH agent auths in this phase's workspace so the
    primary agent can shell out one-shot to the other CLI (codex -> ``claude
    -p`` or claude -> ``codex exec``). Headless providers only. Default false
    preserves single-provider isolation. See
    docs/superpowers/plans/2026-07-23-codex-claude-delegation.md."""

    @field_validator("provider", mode="before")
    @classmethod
    def _reject_removed_provider(cls, value: object) -> object:
        """Fail a workflow that still declares the removed interactive provider.

        ``claude-interactive`` was the interactive-tmux pane path. It was a
        failed experiment (send race, pane-scrape completion heuristic, empty
        observability timelines) and has been removed. Rejecting here - rather
        than silently remapping to ``claude`` - is deliberate: the workflow was
        authored against an interactive REPL, so quietly running it headless
        would change what the phase does without telling the author.

        ``mode="before"`` so this fires ahead of the ``Literal`` check and the
        author sees the removal, not a generic enum error.
        """
        if value == REMOVED_INTERACTIVE_PROVIDER:
            msg = (
                f"agent.provider={REMOVED_INTERACTIVE_PROVIDER!r} has been removed. "
                "The interactive-tmux workspace path no longer exists; every phase "
                f"now runs headless. Use '{AgentProvider.CLAUDE}' (claude -p) or "
                f"'{AgentProvider.CODEX}' (codex exec) instead."
            )
            raise ValueError(msg)
        return value


class PhaseYamlDefinition(BaseModel):
    """Phase definition as parsed from YAML.

    Converts YAML snake_case to domain PhaseDefinition.
    """

    model_config = ConfigDict(
        frozen=True,
        # WHY (#961): a misspelled key used to be accepted and dropped, so a phase
        # whose `prompt:` should have been `prompt_template:` installed cleanly,
        # executed, billed, and gave the agent NO instructions -- with every layer
        # reporting success. Four shipped trigger workflows were also declaring
        # `tools:` (not `allowed_tools:`), silently discarding their intended tool
        # allowlist. Rejecting an unknown key is the only signal an author gets.
        extra="forbid",
    )

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
    prompt_file: str | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None
    allowed_tools: list[str] = Field(default_factory=list)

    # Claude Code command extensions (ISS-211)
    argument_hint: str | None = None
    model: str | None = None

    # Per-phase agent provider selection.
    # ``agent.model`` is a fallback for the top-level ``model`` field.
    agent: AgentYamlDefinition | None = None

    # Phase-scope claude plugin refs (issue #726). Workflow-scope refs live on
    # WorkflowDefinition. PR1 carries them through; PR2 resolves them.
    claude_plugins: list[ClaudePluginRef] = Field(default_factory=list)
    # Phase-scope skill refs (issue #772). Additive alongside claude_plugins.
    # Workflow-scope refs live on WorkflowDefinition; phase scope wins on
    # identity collision when the two lists are merged at resolution time.
    skills: list[SkillRef] = Field(default_factory=list)

    @field_validator("skills", mode="before")
    @classmethod
    def _expand_skills(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        expanded: list[SkillRef] = []
        for entry in value:
            expanded.extend(expand_skill_entry(entry))
        return expanded

    @model_validator(mode="after")
    def validate_prompt_source(self) -> PhaseYamlDefinition:
        """Ensure exactly one of prompt_template or prompt_file is set.

        The "at least one" half is a second, independent guard for #961. A phase
        with no instructions cannot do useful work, so dispatching it to an agent
        is never correct -- but that is exactly what happened when a misspelled
        `prompt:` key was silently dropped: the run completed, billed, and the
        agent spent its turns hunting for a task file it was never given.
        Rejecting the empty case catches that class from the opposite direction
        from `extra="forbid"`, so a future field-name drift cannot reproduce it.
        """
        if self.prompt_template is not None and self.prompt_file is not None:
            msg = f"Phase '{self.id}': specify either 'prompt_template' or 'prompt_file', not both"
            raise ValueError(msg)
        if self.prompt_template is None and self.prompt_file is None:
            msg = (
                f"Phase '{self.id}': needs 'prompt_template' or 'prompt_file'. "
                "A phase with no instructions would run an agent with an empty prompt."
            )
            raise ValueError(msg)
        return self

    def to_domain(self) -> PhaseDefinition:
        """Convert to domain PhaseDefinition.

        Raises:
            ValueError: If prompt_file was set but not resolved via from_file().
        """
        if self.prompt_file is not None and self.prompt_template is None:
            msg = (
                f"Phase '{self.id}': prompt_file '{self.prompt_file}' was not resolved. "
                "Use WorkflowDefinition.from_file() instead of from_yaml() "
                "for workflows with prompt_file references."
            )
            raise ValueError(msg)

        # Per-phase agent block. When absent, leave provider as None so the
        # domain default ("claude") applies. Top-level model wins;
        # agent.model is the fallback.
        provider = self.agent.provider if self.agent else None
        agent_model = self.agent.model if self.agent else None
        allow_delegation = self.agent.allow_delegation if self.agent else False
        model = self.model or agent_model

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
            allowed_tools=self.allowed_tools,
            argument_hint=self.argument_hint,
            model=model,
            provider=provider,
            allow_delegation=allow_delegation,
            claude_plugins=tuple(self.claude_plugins),
            skills=tuple(self.skills),
        )


class PhaseFrontmatterSchema(BaseModel):
    """Schema for the YAML frontmatter in phase .md prompt files.

    This models only the optional metadata fields that appear in phase markdown
    frontmatter — NOT the full phase definition (which includes required fields
    like id/name/order that come from workflow.yaml, not frontmatter).

    Source of truth for schemas/plugin/phase-frontmatter.schema.json.
    See ADR-053 for the schema generation strategy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str | None = Field(
        default=None, description="Model to use for this phase (e.g., 'sonnet', 'opus')."
    )
    allowed_tools: str | list[str] = Field(
        default_factory=list,
        description="Tools available during this phase. "
        "Accepts a YAML list or a comma-separated string (e.g., 'bash, git, read').",
        alias="allowed-tools",
    )
    max_tokens: int | None = Field(
        default=None, description="Maximum tokens for this phase.", alias="max-tokens"
    )
    timeout_seconds: int | None = Field(
        default=None, description="Phase timeout in seconds.", alias="timeout-seconds"
    )
    execution_type: PhaseExecutionType | None = Field(
        default=None,
        description="Phase execution type ('sequential', 'parallel', or 'human_in_loop').",
        alias="execution-type",
    )
    description: str | None = Field(default=None, description="What this phase does.")
    argument_hint: str | None = Field(
        default=None, description="Hint for Claude Code command argument.", alias="argument-hint"
    )


class WorkflowDefinition(BaseModel):
    """Complete workflow definition as parsed from YAML.

    This is the root model for workflow YAML files.
    """

    model_config = ConfigDict(
        frozen=True,
        # Same reasoning as PhaseYamlDefinition (#961): silently dropping an
        # unknown workflow-level key hides an authoring mistake behind a green run.
        extra="forbid",
    )

    # Identity
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

    # Classification
    type: str = "custom"
    classification: WorkflowClassification = WorkflowClassification.STANDARD

    # Repository context
    repository: RepositoryConfig | None = None

    # Execution gate (ADR-058 #666): None = infer from repository presence
    requires_repos: bool | None = None

    # Project association
    project_name: str | None = None

    # Input declarations (ISS-211)
    inputs: list[InputYamlDefinition] = Field(default_factory=list)

    # Phases
    phases: list[PhaseYamlDefinition] = Field(..., min_length=1)

    # Workflow-scope claude plugin refs (issue #726). The Phase 5 resolution
    # service walks both this list and per-phase refs to populate the lock.
    claude_plugins: list[ClaudePluginRef] = Field(default_factory=list)
    # Workflow-scope skill refs (issue #772). Additive alongside
    # claude_plugins. The resolution service walks both this list and
    # per-phase refs to populate the lock, with phase scope winning on
    # identity collision.
    skills: list[SkillRef] = Field(default_factory=list)

    @field_validator("skills", mode="before")
    @classmethod
    def _expand_skills(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        expanded: list[SkillRef] = []
        for entry in value:
            expanded.extend(expand_skill_entry(entry))
        return expanded

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
        """Parse workflow definition from YAML string.

        Note: prompt_file references are NOT resolved here (no base_dir).
        Use from_file() for workflows that reference external .md files.
        """
        data = yaml.safe_load(content)
        return cls.model_validate(data)

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        base_dir: Path | None = None,
        phase_library_dir: Path | None = None,
    ) -> WorkflowDefinition:
        """Load workflow definition from a YAML file.

        Resolves prompt_file references relative to base_dir (defaults to
        the YAML file's parent directory).  ``shared://`` references are
        resolved against *phase_library_dir* when provided.

        Args:
            path: Path to the YAML workflow file.
            base_dir: Base directory for resolving prompt_file paths.
                Defaults to path.parent.
            phase_library_dir: Directory containing shared ``.md`` files
                for ``shared://`` references.
        """
        resolved_base = base_dir or path.parent
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            msg = "Workflow YAML must be a mapping at the root level"
            raise ValueError(msg)
        cls._resolve_prompt_files(data, resolved_base, phase_library_dir=phase_library_dir)
        return cls.model_validate(data)

    @classmethod
    def _resolve_prompt_files(
        cls,
        data: dict[str, Any],
        base_dir: Path,
        *,
        phase_library_dir: Path | None = None,
    ) -> None:
        """Resolve prompt_file references in-place on the raw YAML dict.

        Args:
            data: Raw parsed YAML dict (mutated in place).
            base_dir: Base directory for resolving relative paths.
            phase_library_dir: Directory for ``shared://`` references.
        """
        phases = data.get("phases")
        if not phases or not isinstance(phases, list):
            return

        for phase in phases:
            if isinstance(phase, dict) and "prompt_file" in phase:
                _resolve_phase_prompt_file(phase, base_dir, phase_library_dir=phase_library_dir)

    def get_domain_phases(self) -> list[PhaseDefinition]:
        """Convert all phases to domain PhaseDefinition objects."""
        return [p.to_domain() for p in self.phases]

    def get_domain_input_declarations(self) -> list[InputDeclaration]:
        """Convert all input declarations to domain InputDeclaration objects."""
        return [i.to_domain() for i in self.inputs]


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


def validate_workflow_yaml(
    content: str,
    *,
    base_dir: Path | None = None,
    phase_library_dir: Path | None = None,
) -> tuple[bool, str | None]:
    """Validate workflow YAML content.

    Args:
        content: YAML content to validate.
        base_dir: If provided, resolve prompt_file references relative
            to this directory. Otherwise, only schema validation is performed.
        phase_library_dir: Directory for ``shared://`` references.

    Returns:
        Tuple of (is_valid, error_message).
    """
    try:
        if base_dir is not None:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                msg = "Workflow YAML must be a mapping at the root level"
                raise ValueError(msg)
            WorkflowDefinition._resolve_prompt_files(
                data, base_dir, phase_library_dir=phase_library_dir
            )
            WorkflowDefinition.model_validate(data)
        else:
            WorkflowDefinition.from_yaml(content)
        return (True, None)
    except Exception as e:
        return (False, str(e))
