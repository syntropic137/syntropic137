"""Phase keys that once meant something and are now refused at authoring time.

A retired key is not a field of `PhaseYamlDefinition`. It is checked BY NAME
before `extra="forbid"` runs, so the author gets a message naming the key, when
it was retired and why, instead of pydantic's generic "Extra inputs are not
permitted" (#1502). A misspelt key still gets the generic refusal (#961).

The key was first accepted, ignored and reported as a warning (#1477
follow-up), for at least two releases, before it was refused here.

This is the AUTHORING policy only. Stored events that carry a retired key are
tolerated by a separate, permanent adapter beside the execution value objects
(`REMOVED_EXECUTABLE_PHASE_KEYS`), because history replays forever whatever
authors are later allowed to write.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RetiredPhaseField:
    """A phase key that is refused, with the reason the author is given."""

    name: str
    retired_by: str
    reason: str


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


def reject_retired_fields(phase: object) -> object:
    """Return `phase` unchanged, or raise naming every retired key it carries.

    Anything that is not a mapping is returned as it came, for the model's own
    validation to refuse.

    Raises:
        ValueError: one line per retired key present, each with its reason.
    """
    if not isinstance(phase, Mapping):
        return phase
    present = [field for field in RETIRED_PHASE_FIELDS if field.name in phase]
    if not present:
        return phase
    msg = " ".join(
        f"phase {phase.get('id')!r}: {field.name!r} is retired ({field.retired_by}) and no longer accepted - "
        f"{field.reason} Delete the line."
        for field in present
    )
    raise ValueError(msg)
