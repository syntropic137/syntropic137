"""Reading events whose type name changed meaning (2026-09-29).

`ExecutionResumed` meant un-pausing before this date and means
resume-from-unfinished after it. A type name cannot be trusted alone, so the
payload SHAPE decides, and an ambiguous one is refused rather than guessed.

See `docs/architecture/orchestration-ubiquitous-language.md`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

#: Present only on the post-rename shape. ANY of them is enough, and all three
#: are listed for a reason: under ADR-023 a stored event that fails typed
#: validation replays as a generic one whose missing fields read as absent, so
#: keying on `resume_execution_id` alone would read a resume that lost its
#: child id as an un-pause - and the at-most-once rule would stop holding
#: exactly when it matters (the #1453 review's finding 4, which
#: `TestTheResumeGuardFailsClosed` pins).
_RESUME_MARKERS = ("resume_execution_id", "inherited_phases", "resume_phase_id")

#: What the message names when it explains a refusal.
_RESUME_MARKER = _RESUME_MARKERS[0]

#: Present only on the pre-rename un-pause shape. `resumed_at` is NOT a
#: discriminator: both shapes carry it.
_UNPAUSE_MARKER = "phase_id"

#: The pre-rename field names, and what each is called now. The concept did
#: not change with the rename, only its name, so every field maps one to one.
_FORKED_FIELD_RENAMES = {
    "fork_execution_id": _RESUME_MARKER,
    "forked_at": "resumed_at",
}


class LegacyEventShapeError(RuntimeError):
    """A stored payload cannot be read as the type its name now means."""


class ResumedEventShape(StrEnum):
    """Which of the two meanings a stored `ExecutionResumed` payload carries."""

    #: Resume-from-unfinished. The only shape that is this event.
    POST_RENAME = "post_rename"
    #: Un-pausing a paused execution. Not a resume; nothing to apply.
    PRE_RENAME_UNPAUSE = "pre_rename_unpause"
    #: Neither marker, or BOTH. Refused rather than resolved by guesswork.
    AMBIGUOUS = "ambiguous"


def payload_of(event: object) -> object:
    """A stored event's payload, whether it replayed typed or generic.

    Under ADR-023 the store falls back to `GenericDomainEvent` when typed
    validation fails, and that class allows extra fields, so `model_dump`
    reaches the stored keys in both cases. Anything without `model_dump` is
    returned as-is for the shape check to reject.
    """
    dump = getattr(event, "model_dump", None)
    return dump() if callable(dump) else event


def shape_of_resumed_payload(payload: object) -> ResumedEventShape:
    """Which meaning `payload` carries. The single decision both readers share.

    BOTH markers is AMBIGUOUS, not POST_RENAME. A payload cannot be an
    un-pause and a resume at once, so the presence of the resume marker is not
    sufficient on its own - reading it as a resume because that branch is
    checked first is how a corrupt or hand-edited record would spend an
    execution's one resume.
    """
    if not isinstance(payload, Mapping):
        return ResumedEventShape.AMBIGUOUS
    resume = any(marker in payload for marker in _RESUME_MARKERS)
    unpause = _UNPAUSE_MARKER in payload
    if resume and not unpause:
        return ResumedEventShape.POST_RENAME
    if unpause and not resume:
        return ResumedEventShape.PRE_RENAME_UNPAUSE
    return ResumedEventShape.AMBIGUOUS


def classify_resumed_payload(payload: object) -> None:
    """Return None when `payload` is a post-rename resume, else raise.

    Refusing is deliberate. Interpreting an un-pause as a resume would record
    that an execution had been resumed when nobody resumed it, and an execution
    may be resumed once - so the mistake is unrecoverable, while a refusal is
    a log line and a fixable migration.

    Takes `object` rather than a mapping type on purpose: this reads a STORED
    payload of unknown shape - deciding its shape is the whole job - so it
    narrows here rather than making every caller assert a shape it cannot know.
    Anything that is not a mapping is not this event and is left alone.
    """
    shape = shape_of_resumed_payload(payload)
    if shape is ResumedEventShape.POST_RENAME:
        return None
    if shape is ResumedEventShape.PRE_RENAME_UNPAUSE:
        msg = (
            "This ExecutionResumed payload is the pre-2026-09-29 shape, which recorded "
            "un-pausing a paused execution, not resuming an unfinished one. It carries "
            f"{_UNPAUSE_MARKER!r} and no {_RESUME_MARKER!r}. Rename the stored type to "
            "ExecutionUnpaused before replaying it."
        )
        raise LegacyEventShapeError(msg)
    msg = (
        "An ExecutionResumed payload is ambiguous: it carries neither "
        f"{_RESUME_MARKER!r} nor {_UNPAUSE_MARKER!r}, or it carries both. Its meaning "
        "cannot be determined and it is not guessed."
    )
    raise LegacyEventShapeError(msg)


def upcast_forked_payload(payload: object) -> object:
    """A pre-rename `ExecutionForked` payload as an `ExecutionResumed` one.

    Copies rather than mutating: the caller's stored payload is what an upcast
    failure has to report, so it must survive the call unchanged. Anything that
    is not a mapping is returned untouched, as a non-payload is not ours to
    interpret.
    """
    if not isinstance(payload, Mapping):
        return payload
    upcast = dict(payload)
    for old_name, new_name in _FORKED_FIELD_RENAMES.items():
        if old_name in upcast:
            upcast[new_name] = upcast.pop(old_name)
    if "cancellation_overridden" not in upcast:
        upcast["cancellation_overridden"] = False
    return upcast
