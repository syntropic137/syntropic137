"""What a phase declared it needs proven, and what the forge showed at collection.

docs/plans/20261015_platform-dispatched-evidence.md §A.2 (PR 5a). RECORDED
ONLY: nothing here decides anything, and no decision reads it yet. The gate
that will (§A.3, PR 5b) is a pure function of this replayed state, so it has to
be on the event stream before the gate can exist.

Two facts, each told to the aggregate at the moment it is known:

  - `DeclaredEvidence`: one entry of a phase's `TASK_RESULT` `evidence` list,
    on `AgentExecutionCompleted`. A malformed entry is kept as an unreadable
    declaration rather than dropped (§A.1): a silent drop would read as "no
    proof needed".
  - `ObservedHead`: one branch as the forge had it while the phase's output
    was collected, on `ArtifactsCollectedForPhase`.

Both are value objects in `value_objects`, because the events carry them and an
event may import nothing else. This module is what reads them: the parse of a
reported `evidence` key, the replay readers, and the per-phase state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Final

from pydantic import TypeAdapter, ValidationError

from syn_domain.contexts.orchestration._shared.evidence_contract import EvidenceRequest
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DeclaredEvidence,
    ObservedHead,
)

logger = logging.getLogger(__name__)

#: How much of a refused entry is quoted back to an operator.
_EXCERPT_LIMIT: Final = 200


def declared_evidence_from_reported(value: object) -> tuple[DeclaredEvidence, ...]:
    """What a phase's `evidence` key declared. Never raises.

    Nothing written (absent or null) declares nothing. Anything else that is
    not a list is ONE unreadable declaration, never zero, for the same
    reason a malformed entry is kept.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        return (DeclaredEvidence.refused(f"evidence is not a list: {_excerpt(value)}"),)
    return tuple(_read_entry(entry) for entry in value)


def _read_entry(entry: object) -> DeclaredEvidence:
    # JSON-mode strict: the entry came out of JSON, and `"pr": "12"` is a
    # string, not a pull request number. Python-mode strict would refuse
    # every `kind`, because no JSON value is an enum instance.
    try:
        return DeclaredEvidence(
            request=EvidenceRequest.model_validate_json(json.dumps(entry), strict=True)
        )
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "entry"
        return DeclaredEvidence.refused(f"{where}: {first['msg']} in {_excerpt(entry)}")


_DECLARED: Final = TypeAdapter(tuple[DeclaredEvidence, ...])
_OBSERVED: Final = TypeAdapter(tuple[ObservedHead, ...])


def read_declared_evidence(raw: object) -> tuple[DeclaredEvidence, ...]:
    """The declarations on a replayed `AgentExecutionCompleted`; empty when absent."""
    if not raw:
        return ()
    try:
        return _DECLARED.validate_python(raw)
    except ValidationError:
        # A stored event the model cannot read is still a declaration: keep
        # that it existed rather than replaying it as "nothing declared".
        logger.warning("Unreadable reported_evidence on a replayed event: %s", _excerpt(raw))
        return (DeclaredEvidence.refused("stored declaration is unreadable"),)


def read_observed_heads(raw: object) -> tuple[ObservedHead, ...]:
    """The heads on a replayed `ArtifactsCollectedForPhase`; empty when absent."""
    if not raw:
        return ()
    try:
        return _OBSERVED.validate_python(raw)
    except ValidationError:
        logger.warning("Unreadable observed_heads on a replayed event: %s", _excerpt(raw))
        return ()


@dataclass
class EvidenceRecord:
    """Per phase, what its latest agent run declared and its collection observed.

    Like `ReviewRecord._reported`, each agent run overwrites its phase's
    declarations, so a retry that declares nothing does not inherit the
    abandoned attempt's requests. Replayed state; nothing reads it to decide.
    """

    _declared: dict[str, tuple[DeclaredEvidence, ...]] = field(default_factory=dict)
    _observed: dict[str, tuple[ObservedHead, ...]] = field(default_factory=dict)

    def report(self, phase_id: str, declared: tuple[DeclaredEvidence, ...]) -> None:
        self._declared[phase_id] = declared

    def observe(self, phase_id: str, heads: tuple[ObservedHead, ...]) -> None:
        self._observed[phase_id] = heads

    def declared(self, phase_id: str) -> tuple[DeclaredEvidence, ...]:
        return self._declared.get(phase_id, ())

    def observed(self, phase_id: str) -> tuple[ObservedHead, ...]:
        return self._observed.get(phase_id, ())


def _excerpt(value: object) -> str:
    try:
        text = json.dumps(value)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= _EXCERPT_LIMIT else text[:_EXCERPT_LIMIT] + "..."
