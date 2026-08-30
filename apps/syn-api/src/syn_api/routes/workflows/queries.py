"""Workflow TEMPLATE query operations and read endpoints."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from syn_api._wiring import ensure_connected, get_projection_mgr
from syn_api.types import (
    Err,
    InputDeclarationResponse,
    Ok,
    PhaseDefinitionResponse,
    PhaseRefResponse,
    Result,
    WorkflowDetail,
    WorkflowError,
    WorkflowSummary,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
        InputDeclarationDetail,
        PhaseDefinitionDetail,
        PhaseRefDetail,
    )

router = APIRouter(prefix="/workflows", tags=["workflows"])

# -- Response Models ----------------------------------------------------------


class WorkflowSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    workflow_type: str
    phase_count: int
    created_at: str | None = None
    runs_count: int = 0
    is_archived: bool = False
    # No default (#955): omitting this let the model invent `True` for every
    # workflow while the stored rows said otherwise. An outward response model
    # must not manufacture domain truth - make omission a construction error.
    requires_repos: bool


class InputDeclarationModel(BaseModel):
    name: str
    description: str | None = None
    required: bool = True
    default: str | None = None


def _ref_response(ref: PhaseRefDetail) -> PhaseRefResponse:
    """Field by field, not `**to_dict()`: an unpacked mapping is unchecked,
    and a renamed field would then fail at runtime instead of at typecheck."""
    return PhaseRefResponse(
        source_url=ref.source_url,
        name=ref.name,
        version=ref.version,
        name_overridden=ref.name_overridden,
        raw=ref.raw,
    )


class PhaseDefinition(BaseModel):
    phase_id: str
    name: str
    order: int = 0
    description: str | None = None
    agent_type: str = ""
    prompt_template: str | None = None
    timeout_seconds: int = 300
    allowed_tools: list[str] = Field(default_factory=list)
    argument_hint: str | None = None
    model: str | None = None
    provider: str | None = None
    # Stored since #1012, readable since #1013. `allow_delegation` is
    # security-relevant -- it stages both agent auths -- so a caller must be
    # able to see it.
    allow_delegation: bool = False
    claude_plugins: list[PhaseRefResponse] = Field(default_factory=list)
    skills: list[PhaseRefResponse] = Field(default_factory=list)


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    workflow_type: str
    classification: str
    phases: list[PhaseDefinition] = Field(default_factory=list)
    input_declarations: list[InputDeclarationModel] = Field(default_factory=list)
    created_at: str | None = None
    runs_count: int = 0
    runs_link: str | None = None
    repository_url: str | None = None
    """Template-level repository URL (single-repo workflows)."""
    repos: list[str] = Field(default_factory=list)
    """Default GitHub URLs for multi-repo workspace hydration (ADR-058)."""
    requires_repos: bool  # required for the same reason as the summary model
    """Whether this workflow requires repository access at execution time (ADR-058 #666)."""


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 20


class ExecutionRunSummary(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    error_message: str | None = None


class ExecutionRunListResponse(BaseModel):
    runs: list[ExecutionRunSummary]
    total: int
    workflow_id: str
    workflow_name: str


class ExecutionHistoryResponse(BaseModel):
    workflow_id: str
    workflow_name: str
    executions: list[dict] = Field(default_factory=list)  # type: ignore[type-arg]
    total_executions: int = 0


class ExportManifestResponse(BaseModel):
    """Structured export of a workflow as a file manifest.

    Each key in ``files`` is a relative path; each value is the file content.
    The CLI writes these to disk to produce an installable package or plugin.
    """

    format: Literal["package", "plugin"]
    workflow_id: str
    workflow_name: str
    files: dict[str, str]


# -- Mapping helpers (single source of truth for phase/input mapping) ---------


def _map_phases(raw_phases: list[PhaseDefinitionDetail] | None) -> list[PhaseDefinitionResponse]:
    """Map domain PhaseDefinitionDetail objects to API response models."""
    return [
        PhaseDefinitionResponse(
            phase_id=p.id,
            name=p.name,
            order=p.order,
            description=p.description,
            agent_type=p.agent_type,
            prompt_template=p.prompt_template,
            timeout_seconds=p.timeout_seconds or 300,
            allowed_tools=list(p.allowed_tools),
            argument_hint=p.argument_hint,
            model=p.model,
            provider=p.provider,
            allow_delegation=p.allow_delegation,
            claude_plugins=[_ref_response(r) for r in p.claude_plugins],
            skills=[_ref_response(r) for r in p.skills],
            execution_type=p.execution_type,
            max_tokens=p.max_tokens,
            input_artifact_types=list(p.input_artifact_types),
            output_artifact_types=list(p.output_artifact_types),
        )
        for p in (raw_phases or [])
    ]


def _map_input_declarations(
    raw_decls: list[InputDeclarationDetail] | None,
) -> list[InputDeclarationResponse]:
    """Map domain InputDeclarationDetail objects to API response models."""
    return [
        InputDeclarationResponse(
            name=d.name,
            description=d.description,
            required=d.required,
            default=d.default,
        )
        for d in (raw_decls or [])
    ]


# -- Service functions (importable by tests) ----------------------------------


async def list_workflows(
    workflow_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    include_archived: bool = False,
) -> Result[list[WorkflowSummary], WorkflowError]:
    """List all workflow templates."""
    await ensure_connected()
    domain_summaries = await get_projection_mgr().workflow_list.query(
        workflow_type_filter=workflow_type,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    return Ok(
        [
            WorkflowSummary(
                id=s.id,
                name=s.name,
                workflow_type=s.workflow_type,
                classification=s.classification,
                phase_count=s.phase_count,
                description=s.description,
                created_at=s.created_at,
                runs_count=s.runs_count,
                is_archived=s.is_archived,
                requires_repos=s.requires_repos,
            )
            for s in domain_summaries
        ]
    )


async def get_workflow(
    workflow_id: str,
) -> Result[WorkflowDetail, WorkflowError]:
    """Get detailed workflow template with fully-mapped phase/input objects."""
    await ensure_connected()
    detail = await get_projection_mgr().workflow_detail.get_by_id(workflow_id)
    if detail is None:
        return Err(WorkflowError.NOT_FOUND, message=f"Workflow {workflow_id} not found")

    return Ok(
        WorkflowDetail(
            id=detail.id,
            name=detail.name,
            description=detail.description,
            workflow_type=detail.workflow_type,
            classification=detail.classification,
            phases=_map_phases(detail.phases),
            input_declarations=_map_input_declarations(detail.input_declarations),
            created_at=detail.created_at,
            runs_count=detail.runs_count,
            repository_url=detail.repository_url,
            repos=list(detail.repos),
            requires_repos=detail.requires_repos,
        )
    )


async def export_workflow(
    workflow_id: str,
    fmt: Literal["package", "plugin"] = "package",
) -> Result[ExportManifestResponse, WorkflowError]:
    """Export a workflow as a structured file manifest.

    Builds the file tree for a workflow package or Claude Code plugin.
    The CLI writes these files to disk to produce an installable directory.
    """
    result = await get_workflow(workflow_id)
    if isinstance(result, Err):
        return result

    detail = result.value
    files: dict[str, str] = {}
    slug = _sanitize_slug(detail.name)

    try:
        if fmt == "plugin":
            _build_plugin_files(detail, slug, files)
        else:
            _build_package_files(detail, files)
    except ValueError as exc:
        return Err(WorkflowError.INVALID_INPUT, message=str(exc))

    return Ok(
        ExportManifestResponse(
            format=fmt,
            workflow_id=detail.id,
            workflow_name=detail.name,
            files=files,
        )
    )


# -- Export helpers -----------------------------------------------------------

_SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

# Characters that require quoting in YAML scalar values.
_YAML_SPECIAL_RE = re.compile(r"[:{}\[\],&*?|>!%#@`\"\'\n]")


def _sanitize_slug(name: str) -> str:
    """Convert a workflow name to a safe slug for file paths."""
    slug = name.lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9._-]", "", slug)
    slug = slug.strip(".-")
    if not slug or not _SAFE_SLUG_RE.match(slug):
        slug = "workflow"
    return slug


def _validate_phase_id(phase_id: str) -> str:
    """Validate a phase ID is safe for use in file paths."""
    if not _SAFE_ID_RE.match(phase_id):
        msg = f"Phase ID contains unsafe characters: {phase_id!r}"
        raise ValueError(msg)
    return phase_id


def _yaml_flow_list(values: list[str]) -> str:
    """A flow list the emitter builds, not string concatenation.

    Quoting each item and joining with ", " is not enough: a value that is a
    perfectly safe standalone scalar can still restructure a FLOW LIST. `a,b`
    reads back as `a,b` on its own and splits into two entries inside
    `[a,b]`, so per-item quoting decided correctly and the surrounding
    context still broke it. The emitter knows both.
    """
    return yaml.safe_dump(values, default_flow_style=True, width=10**9).strip().rstrip("\n")


def _yaml_quote(value: str) -> str:
    """Quote a YAML string unless the bare form reads back as itself.

    Special CHARACTERS are not the whole risk. A value made entirely of
    ordinary characters can still change type: bare `null` parses as None and
    erases the field, `123` becomes an int a string field then rejects, and
    `true`/`no`/`on` become booleans. Those look nothing like injection while
    reading the emitted file, which is why the character test missed them.

    So the check is behavioural rather than syntactic: emit the bare form,
    parse it, and quote unless it survives as the same string. That covers
    every YAML scalar resolution rule without this function having to know
    them.
    """
    if _YAML_SPECIAL_RE.search(value) or not _reads_back_as_itself(value):
        # Delegate to the YAML emitter rather than hand-rolling the escape.
        # A hand-written double-quoted scalar keeps PHYSICAL newlines, and
        # YAML folds those to a single space -- so "A\nB" reinstalled as
        # "A B". A NUL produced a document PyYAML refuses outright. The
        # emitter knows every escape; this function only decides WHETHER.
        #
        # Emitted inside a one-item flow list and unwrapped, so there is no
        # document-end marker to trim off a bare scalar dump.
        return _yaml_flow_list([value])[1:-1]
    return value


def _reads_back_as_itself(value: str) -> bool:
    """Whether the bare scalar parses back to the identical string."""
    try:
        return yaml.safe_load(value) == value
    except yaml.YAMLError:
        return False


# -- Export file builders -----------------------------------------------------


def _build_phase_md(phase: PhaseDefinitionResponse) -> str:
    """Build a .md file with YAML frontmatter from a phase definition.

    Uses kebab-case keys matching what md_prompt_loader.py expects on import.
    """
    frontmatter_lines: list[str] = []

    if phase.model:
        frontmatter_lines.append(f"model: {_yaml_quote(phase.model)}")
    if phase.argument_hint:
        frontmatter_lines.append(f"argument-hint: {_yaml_quote(phase.argument_hint)}")
    if phase.allowed_tools:
        frontmatter_lines.append(f"allowed-tools: {','.join(phase.allowed_tools)}")
    if phase.timeout_seconds and phase.timeout_seconds != 300:
        frontmatter_lines.append(f"timeout-seconds: {phase.timeout_seconds}")
    if phase.max_tokens is not None:
        frontmatter_lines.append(f"max-tokens: {phase.max_tokens}")

    body = phase.prompt_template or ""

    if frontmatter_lines:
        frontmatter = "\n".join(frontmatter_lines)
        return f"---\n{frontmatter}\n---\n\n{body}\n"
    return f"{body}\n"


def _yaml_input_lines(detail: WorkflowDetail) -> list[str]:
    """Build the ``inputs:`` block lines for workflow.yaml."""
    if not detail.input_declarations:
        return []
    lines: list[str] = ["", "inputs:"]
    for decl in detail.input_declarations:
        lines.append(f"  - name: {_yaml_quote(decl.name)}")
        if decl.description:
            lines.append(f"    description: {_yaml_quote(decl.description)}")
        lines.append(f"    required: {str(decl.required).lower()}")
        if decl.default is not None:
            lines.append(f"    default: {_yaml_quote(decl.default)}")
    return lines


def _yaml_agent_lines(phase: PhaseDefinitionResponse) -> list[str]:
    """The `agent:` block, in the spelling the packaged workflow YAML uses.

    Emitted only when the phase actually declares something. A bare
    `agent: {}` would be noise, and `provider: null` would assert a choice
    the author never made.
    """
    entries: list[str] = []
    if phase.provider:
        entries.append(f"      provider: {_yaml_quote(phase.provider)}")
    if phase.model:
        entries.append(f"      model: {_yaml_quote(phase.model)}")
    if phase.allow_delegation:
        entries.append("      allow_delegation: true")
    return ["    agent:", *entries] if entries else []


def _yaml_ref_entry(key: str, ref: PhaseRefResponse) -> list[str]:
    """One ref, in the spelling ITS loader accepts.

    Skills and plugins are not symmetric and treating them as one shape
    silently changed identities: `expand_skill_entry` reads `names:`, while
    the plugin validator ignores `names` and derives the name from the source
    basename -- so a plugin exported with `names: [custom]` reinstalled as
    `bar`.

    A ref known only as shorthand becomes a scalar entry. Writing
    `- source: owner/repo@v1` with no `version` produced a mapping BOTH
    reference models reject, so the package would not reinstall.

    Extracted from `_yaml_ref_lines` to stay under the cognitive-complexity
    threshold; the branching is inherent to the two loaders differing.
    """
    if ref.source_url:
        lines = [f"      - source: {_yaml_quote(ref.source_url)}"]
        # Only when the author actually overrode it. Emitting a name that was
        # DERIVED from the source basename makes the loader reconstruct the
        # ref with `name_overridden=True` -- changing provenance the phase
        # never declared. When it was not overridden the loader derives the
        # same name from the source anyway.
        if ref.name and ref.name_overridden:
            plural = key == "skills"
            spelling = "names" if plural else "name"
            value = _yaml_flow_list([ref.name]) if plural else _yaml_quote(ref.name)
            lines.append(f"        {spelling}: {value}")
        if ref.version:
            lines.append(f"        version: {_yaml_quote(ref.version)}")
        return lines
    if ref.raw:
        return [f"      - {_yaml_quote(ref.raw)}"]
    # Neither: unnameable. Dropping it is honest; `source: null` would export
    # a reference that cannot resolve.
    return []


def _yaml_ref_lines(key: str, refs: list[PhaseRefResponse]) -> list[str]:
    """Plugin/skill refs, never joined into `source/name@version`.

    #1014 established that joining corrupts a ref whose source already ends
    in the repo name -- it reparses to a different repository.
    """
    entries = [line for ref in refs for line in _yaml_ref_entry(key, ref)]
    return [f"    {key}:", *entries] if entries else []


def _yaml_phase_lines(phase: PhaseDefinitionResponse) -> list[str]:
    """Build the phase entry lines for a single phase in workflow.yaml."""
    pid = _validate_phase_id(phase.phase_id)
    lines = [
        f"  - id: {pid}",
        f"    name: {_yaml_quote(phase.name)}",
        f"    order: {phase.order}",
        f"    execution_type: {phase.execution_type}",
    ]
    if phase.description:
        lines.append(f"    description: {_yaml_quote(phase.description)}")
    lines.append(f"    prompt_file: phases/{pid}.md")
    if phase.input_artifact_types:
        lines.append(f"    input_artifacts: {_yaml_flow_list(list(phase.input_artifact_types))}")
    if phase.output_artifact_types:
        lines.append(f"    output_artifacts: {_yaml_flow_list(list(phase.output_artifact_types))}")
    # Everything below was silently dropped (#1015). Export emitted 6 of 18
    # fields, so export -> reinstall produced a DIFFERENT workflow rather than
    # an incomplete one: no tool scoping, no provider, no timeouts, no skills.
    #
    # Each guarded on presence, never emitted as an empty value: writing
    # `allowed_tools: []` would turn "inherits the default" into "explicitly
    # declares nothing", which reinstalls differently again.
    if phase.timeout_seconds is not None:
        lines.append(f"    timeout_seconds: {phase.timeout_seconds}")
    # `max_tokens` is deliberately NOT exported. `PhaseYamlDefinition`
    # rejects it -- "no agent CLI exposes a token cap, so this value has never
    # bounded anything" -- so emitting it produced a package that could never
    # be installed. A phase can only carry one via the untyped JSON create
    # path, which is its own defect (#1015 follow-up); exporting it would
    # propagate that anomaly into a file the loader refuses.
    if phase.argument_hint:
        lines.append(f"    argument_hint: {_yaml_quote(phase.argument_hint)}")
    if phase.allowed_tools:
        lines.append(f"    allowed_tools: {_yaml_flow_list(list(phase.allowed_tools))}")
    lines.extend(_yaml_agent_lines(phase))
    lines.extend(_yaml_ref_lines("claude_plugins", phase.claude_plugins))
    lines.extend(_yaml_ref_lines("skills", phase.skills))
    return lines


def _build_workflow_yaml(detail: WorkflowDetail) -> str:
    """Build workflow.yaml content from a WorkflowDetail.

    Phase definitions use ``prompt_file`` references to external .md files,
    matching the format that ``WorkflowDefinition.from_file()`` expects.
    Paths are always relative to the workflow.yaml location.
    """
    lines: list[str] = [
        f"id: {detail.id}",
        f"name: {_yaml_quote(detail.name)}",
        f"description: {_yaml_quote(detail.description or '')}",
        f"type: {detail.workflow_type}",
        f"classification: {detail.classification}",
        *_yaml_input_lines(detail),
        "",
        "phases:",
    ]
    for phase in sorted(detail.phases, key=lambda p: p.order):
        lines.extend(_yaml_phase_lines(phase))
    return "\n".join(lines) + "\n"


def _build_readme(detail: WorkflowDetail) -> str:
    """Build README.md for an exported package."""
    phase_list = "\n".join(
        f"- **Phase {p.order}:** {p.name}" for p in sorted(detail.phases, key=lambda p: p.order)
    )
    return (
        f"# {detail.name}\n\n"
        f"{detail.description or ''}\n\n"
        f"## Usage\n\n"
        f"```bash\n"
        f"syn workflow install .\n"
        f'syn workflow run {detail.id} --task "Your task here"\n'
        f"```\n\n"
        f"## Phases\n\n"
        f"{phase_list}\n"
    )


def _build_manifest_json(detail: WorkflowDetail, slug: str) -> str:
    """Build syntropic137-plugin.json manifest."""
    import json

    manifest = {
        "manifest_version": 1,
        "name": slug,
        "version": "0.1.0",
        "description": detail.description or detail.name,
    }
    return json.dumps(manifest, indent=2) + "\n"


def _build_cc_command(detail: WorkflowDetail, slug: str) -> str:
    """Build a Claude Code command wrapper .md file."""
    return (
        f"---\n"
        f"model: sonnet\n"
        f'argument-hint: "<task>"\n'
        f"allowed-tools: Bash\n"
        f"---\n\n"
        f"# /syn-{slug} — Run {detail.name} Workflow\n\n"
        f"Execute the {slug} workflow via Syntropic137:\n\n"
        f"```bash\n"
        f'syn workflow run {detail.id} --task "$ARGUMENTS"\n'
        f"```\n"
    )


def _build_package_files(
    detail: WorkflowDetail,
    files: dict[str, str],
) -> None:
    """Populate ``files`` dict with package format structure."""
    files["workflow.yaml"] = _build_workflow_yaml(detail)
    files["README.md"] = _build_readme(detail)

    for phase in detail.phases:
        pid = _validate_phase_id(phase.phase_id)
        files[f"phases/{pid}.md"] = _build_phase_md(phase)


def _build_plugin_files(
    detail: WorkflowDetail,
    slug: str,
    files: dict[str, str],
) -> None:
    """Populate ``files`` dict with plugin format structure."""
    files["syntropic137-plugin.json"] = _build_manifest_json(detail, slug)
    files["README.md"] = _build_readme(detail)
    files[f"commands/syn-{slug}.md"] = _build_cc_command(detail, slug)

    wf_prefix = f"workflows/{slug}"
    files[f"{wf_prefix}/workflow.yaml"] = _build_workflow_yaml(detail)

    for phase in detail.phases:
        pid = _validate_phase_id(phase.phase_id)
        files[f"{wf_prefix}/phases/{pid}.md"] = _build_phase_md(phase)


# -- HTTP Endpoints -----------------------------------------------------------


_SORTABLE_SUMMARY_FIELDS: frozenset[str] = frozenset(
    {"runs_count", "name", "workflow_type", "phase_count", "created_at"}
)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows_endpoint(
    workflow_type: str | None = Query(None, description="Filter by workflow type"),
    include_archived: bool = Query(False, description="Include archived workflows"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_by: str | None = Query(None, description="Sort field (- prefix = descending)"),
) -> WorkflowListResponse:
    """List all workflow templates."""
    offset = (page - 1) * page_size
    result = await list_workflows(
        workflow_type=workflow_type,
        limit=page_size,
        offset=offset,
        include_archived=include_archived,
    )
    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    summaries = [
        WorkflowSummaryResponse(
            id=s.id,
            name=s.name,
            workflow_type=s.workflow_type,
            phase_count=s.phase_count,
            created_at=str(s.created_at) if s.created_at else None,
            runs_count=s.runs_count,
            is_archived=s.is_archived,
            # WHY (#955): omitting this let WorkflowSummaryResponse's `= True`
            # default answer for every workflow. Measured on a live deployment:
            # the list reported requires_repos=True for all 36 while the detail
            # endpoint reported False for 20 of them, and the stored rows agreed
            # with detail. An agent that lists workflows, sees True, and passes
            # -R is then told repos are supported when they are not.
            requires_repos=s.requires_repos,
        )
        for s in result.value
    ]

    # KNOWN LIMITATION: this sorts the current PAGE, not the collection, so
    # `order_by` with more than one page does not give a global ordering.
    # Deliberately not pushed into the store yet: it orders on data->>'field',
    # which is text, so runs_count and phase_count would sort lexically
    # ("10" < "9"). Fixing it needs numeric casts in the query builder.
    if order_by:
        desc, field = order_by.startswith("-"), order_by.lstrip("-")
        if field in _SORTABLE_SUMMARY_FIELDS:
            summaries.sort(key=lambda s: getattr(s, field) or 0, reverse=desc)

    # `total` is the size of the whole filtered collection, NOT of this page.
    # It was previously `len(summaries)`, which reported the page size and told
    # a caller on page 1 of 32 records that there were only 20 -- so a client
    # that paginates until it has `total` items stopped after the first page.
    total = await get_projection_mgr().workflow_list.count(
        workflow_type_filter=workflow_type,
        include_archived=include_archived,
    )
    return WorkflowListResponse(
        # No slice here: `list_workflows` already applied limit/offset. Slicing
        # again applied the offset twice, so page 2 sliced [20:40] of a 12-row
        # page and returned nothing.
        workflows=summaries,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow_endpoint(workflow_id: str) -> WorkflowResponse:
    """Get workflow details by ID (supports partial ID prefix matching)."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    workflow_id = await resolve_or_raise(mgr.store, "workflow_details", workflow_id, "Workflow")
    result = await get_workflow(workflow_id)
    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    detail = result.value
    return WorkflowResponse(
        id=detail.id,
        name=detail.name,
        description=detail.description,
        workflow_type=detail.workflow_type,
        classification=detail.classification,
        phases=[
            PhaseDefinition(
                phase_id=p.phase_id,
                name=p.name,
                order=p.order,
                description=p.description,
                agent_type=p.agent_type,
                prompt_template=p.prompt_template,
                timeout_seconds=p.timeout_seconds,
                allowed_tools=list(p.allowed_tools),
                argument_hint=p.argument_hint,
                model=p.model,
                provider=p.provider,
                allow_delegation=p.allow_delegation,
                # Already PhaseRefResponse here: `get_workflow()` mapped the
                # read model at the first build site, so converting again
                # would be a second translation of the same value.
                claude_plugins=list(p.claude_plugins),
                skills=list(p.skills),
            )
            for p in detail.phases
        ],
        input_declarations=[
            InputDeclarationModel(
                name=d.name,
                description=d.description,
                required=d.required,
                default=d.default,
            )
            for d in detail.input_declarations
        ],
        created_at=str(detail.created_at) if detail.created_at else None,
        runs_count=detail.runs_count,
        runs_link=f"/api/workflows/{detail.id}/runs",
        repository_url=detail.repository_url,
        repos=list(detail.repos),
        requires_repos=detail.requires_repos,
    )


@router.get("/{workflow_id}/export", response_model=ExportManifestResponse)
async def export_workflow_endpoint(
    workflow_id: str,
    format: Literal["package", "plugin"] = Query(
        "package",
        description="Export format: 'package' (workflow.yaml + phases) or 'plugin' (full CC plugin)",
    ),
) -> ExportManifestResponse:
    """Export a workflow as a distributable package or Claude Code plugin."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    workflow_id = await resolve_or_raise(mgr.store, "workflow_details", workflow_id, "Workflow")
    result = await export_workflow(workflow_id, fmt=format)
    if isinstance(result, Err):
        if result.error == WorkflowError.NOT_FOUND:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        raise HTTPException(status_code=422, detail=result.message)
    return result.value


@router.get("/{workflow_id}/runs", response_model=ExecutionRunListResponse)
async def list_workflow_runs_endpoint(workflow_id: str) -> ExecutionRunListResponse:
    """List all execution runs for a workflow."""
    from syn_api.prefix_resolver import resolve_or_raise
    from syn_api.routes.executions.queries import list_ as ex_list_

    mgr = get_projection_mgr()
    workflow_id = await resolve_or_raise(mgr.store, "workflow_details", workflow_id, "Workflow")
    wf_result = await get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    workflow_name = wf_result.value.name
    exec_result = await ex_list_(workflow_id=workflow_id)
    if isinstance(exec_result, Err):
        raise HTTPException(status_code=500, detail=exec_result.message)

    return ExecutionRunListResponse(
        runs=[
            ExecutionRunSummary(
                workflow_execution_id=e.workflow_execution_id,
                workflow_id=e.workflow_id,
                workflow_name=e.workflow_name or workflow_name,
                status=e.status,
                started_at=str(e.started_at) if e.started_at else None,
                completed_at=str(e.completed_at) if e.completed_at else None,
                completed_phases=e.completed_phases,
                total_phases=e.total_phases,
                total_tokens=e.total_tokens,
                total_cost_usd=Decimal(str(e.total_cost_usd)),
                error_message=e.error_message,
            )
            for e in exec_result.value
        ],
        total=len(exec_result.value),
        workflow_id=workflow_id,
        workflow_name=workflow_name,
    )


@router.get("/{workflow_id}/history", response_model=ExecutionHistoryResponse)
async def get_workflow_history_endpoint(workflow_id: str) -> ExecutionHistoryResponse:
    """DEPRECATED: Use /workflows/{workflow_id}/runs instead."""
    from syn_api.prefix_resolver import resolve_or_raise

    mgr = get_projection_mgr()
    workflow_id = await resolve_or_raise(mgr.store, "workflow_details", workflow_id, "Workflow")
    wf_result = await get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return ExecutionHistoryResponse(
        workflow_id=workflow_id,
        workflow_name=wf_result.value.name,
        executions=[],
        total_executions=0,
    )
