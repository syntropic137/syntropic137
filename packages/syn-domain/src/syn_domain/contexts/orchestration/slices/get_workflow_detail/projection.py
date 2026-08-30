"""Projection for workflow TEMPLATE detail view.

This projection maintains workflow TEMPLATE (definition) details.
For execution details, see WorkflowExecutionDetailProjection.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.constants import (
    PhaseDefaults,
    PhaseFields,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
    InputDeclarationDetail,
    PhaseDefinitionDetail,
    WorkflowDetail,
)


def _find_phase(phases: list[dict[str, Any]], phase_id: str) -> dict[str, Any] | None:
    """Find a phase dict by ID, checking both 'id' and 'phase_id' keys."""
    for phase in phases:
        pid = phase.get(PhaseFields.ID, phase.get(PhaseFields.PHASE_ID, ""))
        if pid == phase_id:
            return phase
    return None


def _render_ref(ref: object) -> str | None:
    """One plugin/skill ref as its canonical string, or None if unnameable.

    Extracted from `_ref_strings` purely to keep each function under the
    cyclomatic threshold; the branching is inherent, because a projected row
    holds whatever the event serialized -- a mapping for a typed ref, or a
    plain string for the shorthand form.
    """
    if isinstance(ref, str):
        return ref
    if not isinstance(ref, dict):
        return None
    name = ref.get("skill_name") or ref.get("name") or ""
    source = ref.get("source_url") or ref.get("source") or ""
    version = ref.get("version") or ""
    joined = "/".join(str(part) for part in (source, name) if part)
    if not joined:
        return str(ref)
    return f"{joined}@{version}" if version else joined


def _ref_strings(refs: Iterable[object] | None) -> tuple[str, ...]:
    """Render plugin/skill refs as strings for the read model.

    The read model is a VIEW, so it carries the canonical spelling rather than
    re-validating into domain objects a reader does not need.
    """
    if not refs:
        return ()
    rendered = (_render_ref(ref) for ref in refs)
    return tuple(text for text in rendered if text is not None)


def _apply_phase_fields(phase: dict[str, Any], event_data: dict[str, Any]) -> None:
    """Apply updated fields from a phase update event onto a phase dict."""
    phase[PhaseFields.PROMPT_TEMPLATE] = event_data.get("prompt_template")
    for event_key, phase_key in (
        ("model", "model"),
        ("provider", "provider"),
        ("timeout_seconds", PhaseFields.TIMEOUT_SECONDS),
        ("allowed_tools", PhaseFields.ALLOWED_TOOLS),
    ):
        if event_data.get(event_key) is not None:
            phase[phase_key] = event_data[event_key]


class WorkflowDetailProjection(AutoDispatchProjection):
    """Builds workflow TEMPLATE detail read model from events.

    Templates don't have execution status. They only track:
    - Definition info (name, type, phases)
    - runs_count (how many times executed)

    For execution status, see WorkflowExecutionDetailProjection.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_details"
    # Deliberately NOT bumped for the agent_id removal (PR #875 review): the
    # reader addresses stored phase dicts by key, so a version-7 row that still
    # carries "agent_id" stays readable and the field simply stops surfacing. A
    # bump would buy nothing and cost a full replay through the coordinator's
    # non-atomic clear-then-delete-checkpoint sequence, which loses the whole
    # read model if the process dies between the two steps.
    VERSION = 8  # v8: surface allow_delegation, claude_plugins, skills (#1013)

    def __init__(self, store: ProjectionStore):
        """Initialize with a projection store."""
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def on_workflow_template_created(self, event_data: dict) -> None:
        """Handle WorkflowTemplateCreated event - create template detail."""
        workflow_id = event_data.get("workflow_id", "")

        # Convert phase data to PhaseDefinitionDetail format
        # Note: older events may use "prompt_template_id" instead of "prompt_template"
        phases_data = event_data.get("phases", [])
        phases = [
            PhaseDefinitionDetail(
                id=p.get(PhaseFields.ID, p.get(PhaseFields.PHASE_ID, f"phase-{i}")),
                name=p.get(PhaseFields.NAME, ""),
                description=p.get(PhaseFields.DESCRIPTION),
                agent_type=p.get(PhaseFields.AGENT_TYPE, PhaseDefaults.AGENT_TYPE),
                order=p.get(PhaseFields.ORDER, i),
                # Check both new and old field names for backwards compatibility
                prompt_template=p.get(PhaseFields.PROMPT_TEMPLATE) or p.get("prompt_template_id"),
                timeout_seconds=p.get(PhaseFields.TIMEOUT_SECONDS, PhaseDefaults.TIMEOUT_SECONDS),
                allowed_tools=tuple(p.get(PhaseFields.ALLOWED_TOOLS, [])),
                argument_hint=p.get("argument_hint"),
                model=p.get("model"),
                provider=p.get("provider"),
                # Stored by create since #1012 and invisible until #1013: a
                # caller could not ask the API what it had installed.
                allow_delegation=bool(p.get("allow_delegation", False)),
                claude_plugins=_ref_strings(p.get("claude_plugins")),
                skills=_ref_strings(p.get("skills")),
                execution_type=p.get("execution_type", "sequential"),
                max_tokens=p.get(PhaseFields.MAX_TOKENS),
                input_artifact_types=tuple(p.get("input_artifact_types", [])),
                output_artifact_types=tuple(p.get("output_artifact_types", [])),
            )
            for i, p in enumerate(phases_data)
        ]

        # Extract input declarations (ISS-211)
        input_decls_data = event_data.get("input_declarations", [])
        input_decls = [
            InputDeclarationDetail(
                name=d.get("name", ""),
                description=d.get("description"),
                required=d.get("required", True),
                default=d.get("default"),
            )
            for d in input_decls_data
        ]

        detail = WorkflowDetail(
            id=workflow_id,
            name=event_data.get("name", ""),
            workflow_type=event_data.get("workflow_type", ""),
            classification=event_data.get("classification", ""),
            description=event_data.get("description"),
            phases=phases,
            input_declarations=input_decls,
            created_at=event_data.get("created_at"),
            runs_count=0,
            repository_url=event_data.get("repository_url"),
            repos=tuple(event_data.get("repos", [])),
            requires_repos=event_data.get("requires_repos", True),
        )
        await self._store.save(self.PROJECTION_NAME, workflow_id, detail.to_dict())

    async def on_workflow_template_updated(self, event_data: dict) -> None:
        """Handle WorkflowTemplateUpdated - rebuild the detail in place (issue #822).

        A reinstall replaces the definition wholesale, so the detail is rebuilt
        from the event exactly as create does. Run history is a property of the
        template, not of the definition, so runs_count and created_at survive.
        """
        workflow_id = event_data.get("workflow_id", "")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        await self.on_workflow_template_created(event_data)

        if not existing:
            return

        rebuilt = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if not rebuilt:
            return
        rebuilt["runs_count"] = existing.get("runs_count", 0)
        if existing.get("created_at"):
            rebuilt["created_at"] = existing["created_at"]
        await self._store.save(self.PROJECTION_NAME, workflow_id, rebuilt)

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted - increment runs_count."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["runs_count"] = existing.get("runs_count", 0) + 1
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def on_workflow_phase_updated(self, event_data: dict) -> None:
        """Handle WorkflowPhaseUpdated event - update phase prompt and config."""
        workflow_id = event_data.get("workflow_id", "")
        phase_id = event_data.get("phase_id", "")
        if not workflow_id or not phase_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if not existing:
            return

        # Update the matching phase in the phases list
        phase = _find_phase(existing.get("phases", []), phase_id)
        if phase is not None:
            _apply_phase_fields(phase, event_data)

        await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def get_by_id(self, workflow_id: str) -> WorkflowDetail | None:
        """Get a workflow template by ID."""
        data = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if data:
            return WorkflowDetail.from_dict(data)
        return None
