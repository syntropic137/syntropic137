"""Phase keys an author may still write, which no longer do anything.

A retired key is not a field of `PhaseYamlDefinition`. It is dropped BY NAME
before `extra="forbid"` runs, so a workflow that still carries it loads, while a
misspelt key is still refused (#961). Each one is reported back to the author as
a notice, so the drop is never silent.

This is the AUTHORING policy only, and it is temporary: a later change rejects
these keys outright. Stored events that carry a retired key are tolerated by a
separate, permanent adapter beside the execution value objects
(`REMOVED_EXECUTABLE_PHASE_KEYS`), because history replays forever whatever
authors are later allowed to write.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RetiredPhaseField:
    """A phase key that is accepted, ignored, and reported."""

    name: str
    retired_by: str
    reason: str


# TODO(#1502): reject these at authoring time once the gate in the issue is met.
RETIRED_PHASE_FIELDS: tuple[RetiredPhaseField, ...] = (
    RetiredPhaseField(
        name="can_open_pr",
        retired_by="#1477",
        reason=(
            "has had no effect since #1477: every phase token carries the "
            "installation's own permissions, so every phase may open and "
            "comment on a PR."
        ),
    ),
)


def without_retired_fields(phase: object) -> object:
    """An authored phase with every retired key removed.

    Anything that is not a mapping is returned as it came, for the model's own
    validation to refuse.
    """
    if not isinstance(phase, Mapping):
        return phase
    retired = {field.name for field in RETIRED_PHASE_FIELDS}
    return {key: value for key, value in phase.items() if key not in retired}


def retired_field_notices(definition: object) -> list[str]:
    """One message per retired key an authored workflow still carries.

    Takes the parsed workflow as it was written, before validation, and never
    raises: anything that is not a mapping with a list of phases has nothing to
    report.
    """
    if not isinstance(definition, Mapping):
        return []
    phases = definition.get("phases")
    if not isinstance(phases, list):
        return []
    notices: list[str] = []
    for phase in phases:
        if not isinstance(phase, Mapping):
            continue
        for field in RETIRED_PHASE_FIELDS:
            if field.name in phase:
                notices.append(
                    f"phase {phase.get('id')!r}: {field.name!r} is retired "
                    f"({field.retired_by}) and ignored - {field.reason} Delete the line."
                )
    return notices
