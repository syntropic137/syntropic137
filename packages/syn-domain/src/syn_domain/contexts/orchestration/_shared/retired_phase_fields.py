"""Phase keys an author may still write, which no longer do anything.

A retired key is dropped by name before a phase is validated, so YAML written
against an older schema still installs, and every path that reads authored YAML
tells the author the line can go. Dropping by NAME keeps `extra="forbid"`
refusing every other unknown key (#961): a misspelling is still an error.

This is the authoring policy only. Stored events that carry a retired key are a
separate, permanent concern of the aggregate that replays them (see
`REMOVED_EXECUTABLE_PHASE_KEYS`), because history replays forever whatever
authors are allowed to write today.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RetiredPhaseField:
    """A phase key that is accepted, ignored, and reported to the author."""

    name: str
    retired_by: str
    reason: str
    """One sentence an author reads: why the key does nothing."""


# TODO(#1496): reject these at authoring time once the issue's gate is met.
RETIRED_PHASE_FIELDS: tuple[RetiredPhaseField, ...] = (
    RetiredPhaseField(
        name="can_open_pr",
        retired_by="#1477",
        reason=(
            "it has had no effect since #1477: every phase token carries the "
            "installation's own permissions, so every phase may open and "
            "comment on a PR."
        ),
    ),
)

_RETIRED_NAMES = frozenset(f.name for f in RETIRED_PHASE_FIELDS)


def without_retired_fields(phase: object) -> object:
    """``phase`` without any retired key, or ``phase`` itself if it is not a mapping."""
    if not isinstance(phase, Mapping) or _RETIRED_NAMES.isdisjoint(phase):
        return phase
    return {k: v for k, v in phase.items() if k not in _RETIRED_NAMES}


def retired_field_notices(definition: object) -> list[str]:
    """One message per retired key per phase of a parsed workflow.

    Never raises: anything that is not a mapping with a ``phases`` list has no
    phases to report on, so it yields nothing and the validator that follows
    is left to explain what is wrong with it.
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
