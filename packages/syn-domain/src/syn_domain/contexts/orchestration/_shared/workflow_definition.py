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
    require_supported_execution_type,
)
from syn_shared.agents import REMOVED_INTERACTIVE_PROVIDER, AgentProvider
from syn_shared.tools import require_supported_tools

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

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(..., min_length=1)
    ref: str = Field(default="main")


#: Input names a workflow may NOT declare, because the execute API refuses them.
#:
#: ADR-063 made repository identity typed on ``repos[]`` rather than smuggled
#: through ``inputs``. The API rejects these at its boundary - but nothing
#: stopped a workflow DECLARING one, and the dashboard renders declared inputs.
#: The result was a form field that could never be submitted by any value
#: (#942). Defined here and imported by the API so the two cannot drift.
RESERVED_INPUT_NAMES: frozenset[str] = frozenset({"repos", "repository"})


class InputYamlDefinition(BaseModel):
    """Input declaration as parsed from YAML.

    Maps to domain InputDeclaration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

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

    # A phase id is INTERPOLATED INTO A FILESYSTEM PATH: outputs from this
    # phase are injected into the next phase's workspace at
    # `artifacts/input/<phase-id>/...`. `min_length=1` alone accepted
    # `../../../tmp/owned`, which escapes the workspace on injection - and with
    # the Docker backend the write lands on the host beside the mount, not
    # merely elsewhere inside the container.
    #
    # Workflows are installable from a marketplace, so the author of a phase id
    # is not necessarily the operator running it. That makes this reachable by
    # an untrusted party, which is what decides the grammar below: an
    # allowlist, not a `..` denylist. Denylists lose to encoding tricks; a
    # closed character set does not.
    id: str = Field(
        ..., alias="id", min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$"
    )
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

    @field_validator("allowed_tools", mode="before")
    @classmethod
    def _validate_tool_names(cls, value: object) -> object:
        """Resolve authored tool names against the closed vocabulary (#964).

        Rejecting here rather than only at execution: while the declaration was
        inert a typo cost nothing, but it now restricts availability, so
        `bash` instead of `Bash` becomes an agent that cannot run a command -
        discovered at runtime, on an unattended CI trigger.

        The RULE lives in `require_supported_tools`, not here. Execution has to
        apply the same one to stored templates that never saw this validator,
        and two copies of a vocabulary check are two things to drift apart.
        """
        if value is None:
            return []
        raw = value.split(",") if isinstance(value, str) else value
        if not isinstance(raw, list):
            return value
        return [str(t) for t in require_supported_tools(raw)]

    @field_validator("max_tokens", mode="before")
    @classmethod
    def _reject_max_tokens(cls, value: object) -> object:
        """`max_tokens` caps nothing, on any harness (#964).

        It is declared, carried into AgentConfiguration, and rendered by the
        workflow-detail projection - so it reads as configuration that works -
        and reaches no command builder. It cannot: neither CLI has a token-cap
        flag. Verified against claude 2.1.251, whose nearest control is
        `--max-budget-usd` (dollars, not tokens), and codex 0.147.0, which has
        neither.

        Failing loudly rather than accepting-and-dropping is the whole point
        of the issue this closes. An author bounding an expensive fan-out
        should learn that this is not the lever, at authoring time.
        """
        if value is None:
            return None
        msg = (
            "max_tokens is not supported: no agent CLI exposes a token cap, so this "
            "value has never bounded anything. Remove it. To bound a phase use "
            "timeout_seconds, or scope the work with allowed_tools."
        )
        raise ValueError(msg)

    @field_validator("execution_type", mode="before")
    @classmethod
    def _reject_unimplemented_execution_types(cls, value: object) -> object:
        """Only `sequential` is implemented; the rest are refused (#1039).

        NOTHING in this repository branches on this field. A search for
        `PhaseExecutionType.PARALLEL` or `.HUMAN_IN_LOOP` outside the enum
        definition returns no processor, no dispatcher and no handler. Every
        phase runs sequentially regardless of what is written here.

        Both non-default members are refused in the same change, deliberately.
        `parallel` is the one the issue names, but `human_in_loop` is the more
        dangerous half: an author who writes it believes a human approves the
        phase before it runs, and no human does. Refusing one and leaving the
        other would certify an open half of the class as closed.

        Refusing rather than implementing: wiring `parallel` to a processor
        that does not exist converts a silent lie into a crash. Refusal is
        honest, cheap, and reversible the day a parallel processor lands.

        This is the EARLY half of the check. The rule itself lives in
        `require_supported_execution_type` because a stored template bypasses
        this validator entirely, so execution re-checks it.
        """
        if value is None:
            return value
        require_supported_execution_type(str(getattr(value, "value", value)))
        return value

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
    def validate_tool_policy_is_supported_by_provider(self) -> PhaseYamlDefinition:
        """Codex has no tool vocabulary, so refuse the combination here (#1009).

        `UnsupportedToolPolicyError` already existed and was already correct,
        but it was raised from the command builder behind
        `if phase.agent_config.allowed_tools:` - the tuple that was always
        empty, so it was unreachable. Wiring `allowed_tools` makes it
        reachable, but dispatch is the wrong place for it: by then the
        workspace is provisioned and the author is paying for it.

        The answer cannot change between authoring and dispatch. Codex
        enforces WHERE a process may write, at the kernel level, and has no
        concept of which tools exist (ADR-069 section 3). So the refusal moves
        to creation, beside the tool-vocabulary check.
        """
        provider = self.agent.provider if self.agent else None
        if provider is None or not self.allowed_tools:
            return self
        if str(provider) != AgentProvider.CODEX:
            return self
        declared = ", ".join(str(t) for t in self.allowed_tools)
        msg = (
            f"Phase '{self.id}': provider 'codex' cannot honour allowed_tools "
            f"({declared}). Codex enforces a filesystem sandbox, not a tool "
            "vocabulary, so a tool list would be accepted and never applied. "
            "Remove allowed_tools, or run this phase on 'claude'."
        )
        raise ValueError(msg)

    @model_validator(mode="after")
    def validate_prompt_source(self) -> PhaseYamlDefinition:
        """Ensure at most one of prompt_template or prompt_file is set.

        NOT enforced here: that at least one is set. A phase with no
        instructions cannot do useful work and should be rejected, but adding
        that guard breaks 21 existing tests whose fixtures omit the prompt, so
        it is split into its own change rather than buried in a PR about
        unknown keys. Tracked separately.
        """
        if self.prompt_template is not None and self.prompt_file is not None:
            msg = f"Phase '{self.id}': specify either 'prompt_template' or 'prompt_file', not both"
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
        description="Tools AVAILABLE during this phase, restricting what the agent "
        "can reach for. Accepts a YAML list or a comma-separated string "
        "(e.g., 'Bash, Read'). Names are Claude built-ins and are validated; "
        "case is forgiven. Omit to leave the phase unrestricted. Not supported "
        "on the codex provider, which has no tool-name concept.",
        alias="allowed-tools",
    )
    max_tokens: int | None = Field(
        default=None,
        description="UNSUPPORTED - declaring it is an error. No harness CLI has a "
        "token-cap flag, so this never bounded anything. Use timeout_seconds.",
        alias="max-tokens",
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

    # Multi-repo templates. `CreateWorkflowTemplateCommand.repos` and the
    # aggregate have carried this since ADR-058, and the docs advertise it
    # (guide/core-concepts, workspaces/hydration), but the YAML model never
    # gained the field -- so a documented `repos:` block was silently dropped.
    # With extra="forbid" that silence becomes a hard error, so the field is
    # added here rather than deleting the documented capability.
    repos: list[str] = Field(default_factory=list)

    # Execution gate (ADR-058 #666). `infer_requires_repos` is the only code
    # that turns an unset value into a verdict; this field carries the
    # author's declaration, nothing more.
    #
    # WHY the description rather than a comment (#1050): this comment used to
    # claim "None = infer from repository presence", which was the pre-v0.25.2
    # rule and had been false since ADR-058 moved to opt-out. A workflow author
    # reading the schema was told their repo-less workflow would run, and it
    # was then rejected at execute time. The schema is what authors validate
    # against, so the rule belongs in the generated schema, not in a comment
    # only this repo can see.
    requires_repos: bool | None = Field(
        default=None,
        description=(
            "Whether executing this workflow requires at least one repository. "
            "Omitting it means true: a workflow that operates on no repos must "
            "opt out with `requires_repos: false`, or execution is rejected "
            "(ADR-058)."
        ),
    )

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

    @field_validator("inputs")
    @classmethod
    def reject_reserved_input_names(
        cls, inputs: list[InputYamlDefinition]
    ) -> list[InputYamlDefinition]:
        """A workflow must not declare an input the execute API will refuse.

        Caught here rather than at run time because the dashboard renders
        declared inputs: a reserved name becomes a field a user can fill and
        can never submit. Failing at definition time also covers workflows
        installed from the marketplace, which nobody reviews by hand.
        """
        offending = sorted({i.name for i in inputs} & RESERVED_INPUT_NAMES)
        if offending:
            names = ", ".join(repr(n) for n in offending)
            msg = (
                f"input name(s) {names} are reserved: repositories are passed in "
                "the typed 'repos' array (CLI: -R <owner/repo>), never as an "
                "input. A workflow declaring one renders a form field the API "
                "always rejects."
            )
            raise ValueError(msg)
        return inputs

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

    @model_validator(mode="after")
    def validate_input_artifacts_resolve(self) -> WorkflowDefinition:
        """Every declared input artifact must have a producer (#1039, ADR-069 D5).

        WHY THIS IS A CHECK AND NOT A FILTER. The obvious reading of #1039 is
        that `input_artifacts` should narrow what a phase receives. It cannot,
        because the declaration and the injection are keyed on different
        vocabularies:

          - injection is keyed on PHASE IDs. `_wiring.py` substitutes
            `{{<phase-id>}}` and builds the context appendix per phase id.
          - declaration is keyed on ARTIFACT TYPES (`input_artifacts` ->
            `input_artifact_types`).

        Measured over all 22 authored multi-phase workflows before this was
        written: 0 declared inputs equal a phase id, and the intersection of
        the two vocabularies across the whole corpus is the empty set. So
        filtering phase outputs by this field would match nothing and every
        phase would receive nothing. That is not a compatibility risk to be
        sized, it is guaranteed breakage.

        What authors actually wrote is coherent - 31 of 33 declarations name a
        prior phase's output type - so the field keeps its meaning as a
        type-level dependency graph and becomes an assertion the platform
        checks. Runtime injection is deliberately untouched.

        THE SOURCE SET IS PRIOR OUTPUTS UNION WORKFLOW INPUTS. Prior outputs
        alone would make a first phase's dependency unexpressible, since it has
        no prior phases and no other spelling available. Authors would then
        delete the field rather than fix it, losing the graph. Including
        workflow inputs turns the one real orphan in the shipped corpus
        (`feature_request` in examples/implementation.yaml, whose workflow
        input is named `task`) into a rename rather than a deletion.

        THIS IS A HARD REJECT, NOT A WARNING, and that is a decision rather
        than an oversight. It is retroactive: reinstalling an already-installed
        workflow carrying an orphan will now fail. That is the point. A
        permissive default nobody sees is indistinguishable from no rule, which
        is precisely how these four fields went inert.
        """
        available: set[str] = {decl.name for decl in self.inputs}
        for phase in sorted(self.phases, key=lambda p: p.order):
            unresolved = [t for t in phase.input_artifacts if t not in available]
            if unresolved:
                producers = ", ".join(sorted(available)) or "nothing"
                msg = (
                    f"Phase '{phase.id}' declares input_artifacts "
                    f"{unresolved} that no earlier phase produces and no "
                    f"workflow input provides. Available at this point: "
                    f"{producers}. Declare the type in an earlier phase's "
                    "output_artifacts, add a matching workflow input, or "
                    "remove it."
                )
                raise ValueError(msg)
            available.update(phase.output_artifacts)
        return self

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
