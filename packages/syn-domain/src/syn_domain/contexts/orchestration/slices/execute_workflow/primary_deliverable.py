"""Which of a phase's deliverables stands for the phase (#2084).

The head of the ranked list is flagged the Primary Deliverable, becomes the
live ``first_content`` and is written as the next phase's flat
``artifacts/input/<phase-id>.md`` alias, so this one ordering decides all
three.
"""

from __future__ import annotations

from typing import Final, Protocol

from syn_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

_OUTPUT_DIR_REL: Final[str] = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT).as_posix()
_MARKDOWN: Final[str] = ".md"


class Deliverable(Protocol):
    """What the ranking reads: where a deliverable came from, and what it holds."""

    @property
    def source_path(self) -> str: ...
    @property
    def content(self) -> str | bytes: ...


def ranked[D: Deliverable](
    deliverables: list[D], *, phase_id: str, primary_path: str | None = None
) -> list[D]:
    """`deliverables` with the one that stands for the phase first; stable.

    A named `primary_path` wins outright: a command phase names
    ``commands.json``, which is binary, and is never left to rank (ADR-078 D7).
    Otherwise binary last (#990), then the phase's own report
    (``artifacts/output/<phase-id>.md``), then any markdown, then the remaining
    text in collection order. A verify phase that wrote ``fitness-ci.log``
    before ``verify.md`` used to hand the next phase a pytest log as its input
    (exec-269d15483078): disk order is not a statement about which file is the
    report.
    """
    report = f"{_OUTPUT_DIR_REL}/{phase_id}{_MARKDOWN}"
    return sorted(
        deliverables,
        key=lambda d: (
            primary_path is not None and d.source_path != primary_path,
            isinstance(d.content, bytes),
            d.source_path != report,
            not d.source_path.endswith(_MARKDOWN),
        ),
    )
