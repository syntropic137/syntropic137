"""Reading events whose type name changed meaning (2026-09-29).

`ExecutionResumed` meant un-pausing before this date and means
resume-from-unfinished after it. A type name cannot be trusted alone, so the
payload SHAPE decides, and an ambiguous one is refused rather than guessed.

See `docs/architecture/orchestration-ubiquitous-language.md`.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Present only on the post-rename shape.
_RESUME_MARKER = "resume_execution_id"

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
    if not isinstance(payload, Mapping):
        return None
    if _RESUME_MARKER in payload:
        return None
    if _UNPAUSE_MARKER in payload:
        msg = (
            "This ExecutionResumed payload is the pre-2026-09-29 shape, which recorded "
            "un-pausing a paused execution, not resuming an unfinished one. It carries "
            f"{_UNPAUSE_MARKER!r} and no {_RESUME_MARKER!r}. Rename the stored type to "
            "ExecutionUnpaused before replaying it."
        )
        raise LegacyEventShapeError(msg)
    msg = (
        "An ExecutionResumed payload carries neither the resume marker "
        f"{_RESUME_MARKER!r} nor the un-pause marker {_UNPAUSE_MARKER!r}; its meaning "
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
