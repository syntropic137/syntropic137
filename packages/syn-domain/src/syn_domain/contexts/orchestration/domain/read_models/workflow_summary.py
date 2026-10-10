"""Read model for workflow list views.

NOTE: Workflow templates do NOT have status. Status belongs to WorkflowExecutions.
Templates are definitions - they're either "active" (usable) or "archived".
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from syn_domain.contexts.orchestration.domain.constants import PhaseFields
from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import PhaseRefDetail


@dataclass(frozen=True)
class WorkflowSkillSummary:
    """One skill a workflow declares, and where it declares it.

    A list card shows a workflow's skills as chips. Without this on the summary
    a client had to fetch every workflow's detail to draw one page of cards:
    one request per workflow, for data the template events already carry.

    The ref is carried whole (see ``PhaseRefDetail``): two refs that differ
    only in version or source are two skills, never one chip.
    """

    ref: PhaseRefDetail
    phase_ids: tuple[str, ...] = ()
    """Phases that declare this skill themselves, in phase order, each once."""
    workflow_scope: bool = False
    """Declared at workflow scope, so every phase gets it (#772).

    Kept apart from ``phase_ids`` rather than expanded into every phase id:
    "this phase asked for it" and "the workflow gave it to every phase" are
    different facts, and a client cannot recover one from the other."""

    @classmethod
    def from_stored(cls, data: object) -> "WorkflowSkillSummary | None":
        """Read one stored row, or None when it names no skill."""
        if not isinstance(data, dict):
            return None
        ref = PhaseRefDetail.from_stored(data.get("ref"))
        if ref is None:
            return None
        raw_phase_ids = data.get("phase_ids")
        phase_ids = (
            tuple(p for p in raw_phase_ids if isinstance(p, str))
            if isinstance(raw_phase_ids, (list, tuple))
            else ()
        )
        return cls(ref=ref, phase_ids=phase_ids, workflow_scope=data.get("workflow_scope") is True)

    def to_dict(self) -> dict[str, dict[str, str | bool | None] | list[str] | bool]:
        return {
            "ref": self.ref.to_dict(),
            "phase_ids": list(self.phase_ids),
            "workflow_scope": self.workflow_scope,
        }


_SkillKey = tuple[str | None, str | None, str | None, str | None]
"""(source_url, version, name, raw): what makes two declared refs one skill.

Keyed as ``SkillRef`` compares, not by the whole ref: ``name_overridden`` is
how a name was spelled, not which skill it is."""


def _readable_refs(refs: object) -> list[PhaseRefDetail]:
    # A tuple when the dispatcher hands over ``model_dump()`` directly, a list
    # once the payload has been through JSON; both are the same refs. An entry
    # that names nothing is dropped, never turned into a blank skill.
    if not isinstance(refs, (list, tuple)):
        return []
    read = (PhaseRefDetail.from_stored(ref) for ref in refs)
    return [ref for ref in read if ref is not None]


def _phase_order(phase: object) -> tuple[int, int]:
    # A phase with no readable order sorts after every ordered one, keeping its
    # place among the others: position breaks every tie.
    order = phase.get(PhaseFields.ORDER) if isinstance(phase, dict) else None
    if isinstance(order, int) and not isinstance(order, bool):
        return (0, order)
    return (1, 0)


def _in_phase_order(phases: Iterable[object]) -> list[object]:
    """The phases sorted by their declared ``order``, not as supplied.

    The events carry phases in whatever sequence the author wrote them; the
    order a phase runs in is its ``order`` field, and "in phase order" means that.
    """
    keyed = [(_phase_order(phase), position, phase) for position, phase in enumerate(phases)]
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    return [phase for _, _, phase in keyed]


def declared_skills(
    phases: Iterable[object], workflow_skills: Iterable[object] = ()
) -> tuple[WorkflowSkillSummary, ...]:
    """Every distinct skill the template declares, first-declared first.

    Workflow-scope refs come first, then each phase's in phase order. Takes
    both as the template events carry them.
    """
    refs: dict[_SkillKey, PhaseRefDetail] = {}
    phase_ids: dict[_SkillKey, list[str]] = {}
    workflow_scope: set[_SkillKey] = set()

    def note(ref: PhaseRefDetail) -> _SkillKey:
        key = (ref.source_url, ref.version, ref.name, ref.raw)
        refs.setdefault(key, ref)
        phase_ids.setdefault(key, [])
        return key

    for ref in _readable_refs(list(workflow_skills)):
        workflow_scope.add(note(ref))
    for phase in _in_phase_order(phases):
        if not isinstance(phase, dict):
            continue
        phase_id = phase.get(PhaseFields.ID) or phase.get(PhaseFields.PHASE_ID) or ""
        for ref in _readable_refs(phase.get("skills")):
            declaring = phase_ids[note(ref)]
            if phase_id and phase_id not in declaring:
                declaring.append(phase_id)
    return tuple(
        WorkflowSkillSummary(
            ref=ref, phase_ids=tuple(phase_ids[key]), workflow_scope=key in workflow_scope
        )
        for key, ref in refs.items()
    )


@dataclass(frozen=True)
class WorkflowSummary:
    """Read model for workflow TEMPLATE list view.

    This is a lightweight DTO optimized for listing workflow templates.
    Templates are definitions - they don't have execution status.
    For execution status, see WorkflowExecutionSummary.
    """

    id: str
    """Unique identifier for the workflow template."""

    name: str
    """Display name of the workflow."""

    workflow_type: str
    """Type of workflow (e.g., 'research', 'implementation')."""

    classification: str
    """Classification category of the workflow."""

    phase_count: int
    """Number of phases in the workflow definition."""

    description: str | None
    """Optional description of the workflow."""

    created_at: datetime | None
    """When the workflow template was created."""

    runs_count: int = 0
    """Number of times this workflow has been executed."""

    is_archived: bool = False
    """Whether this workflow template has been archived."""

    requires_repos: bool = True
    """Whether this workflow requires repository access at execution time (ADR-058 #666)."""

    tags: tuple[str, ...] = ()
    """The template's tags, normalised and sorted (#967). Future runs inherit them."""

    skills: tuple[WorkflowSkillSummary, ...] = ()
    """Every distinct skill the template declares, workflow scope and per phase."""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowSummary":
        """Create from dictionary data."""
        return cls(
            id=data["id"],
            name=data["name"],
            workflow_type=data.get("workflow_type", ""),
            classification=data.get("classification", ""),
            phase_count=data.get("phase_count", 0),
            description=data.get("description"),
            created_at=data.get("created_at"),
            runs_count=data.get("runs_count", 0),
            is_archived=data.get("is_archived", False),
            requires_repos=data.get("requires_repos", True),
            tags=tuple(data.get("tags") or ()),
            skills=tuple(
                skill
                for skill in (WorkflowSkillSummary.from_stored(s) for s in data.get("skills") or ())
                if skill is not None
            ),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        # Handle created_at which could be datetime or already a string
        created_at_str = None
        if self.created_at:
            created_at_str = (
                self.created_at.isoformat()
                if isinstance(self.created_at, datetime)
                else str(self.created_at)
            )

        return {
            "id": self.id,
            "name": self.name,
            "workflow_type": self.workflow_type,
            "classification": self.classification,
            "phase_count": self.phase_count,
            "description": self.description,
            "created_at": created_at_str,
            "runs_count": self.runs_count,
            "is_archived": self.is_archived,
            "requires_repos": self.requires_repos,
            "tags": list(self.tags),
            "skills": [s.to_dict() for s in self.skills],
        }
