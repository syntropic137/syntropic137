"""Which of a phase's deliverables stands for the phase (#2084).

The head of the ranked list is flagged the Primary Deliverable, becomes the
live ``first_content`` and is written as the next phase's flat
``artifacts/input/<phase-id>.md`` alias, so this one key decides all three.
"""

from __future__ import annotations

from typing import Final

from syn_shared.workspace_paths import WORKSPACE_OUTPUT_DIR, WORKSPACE_ROOT

_OUTPUT_DIR_REL: Final[str] = WORKSPACE_OUTPUT_DIR.relative_to(WORKSPACE_ROOT).as_posix()
_MARKDOWN: Final[str] = ".md"


def primary_rank(
    source_path: str, content: str | bytes, *, phase_id: str
) -> tuple[bool, bool, bool]:
    """Sort key for a deliverable; lower is first, and equal keys keep collection order.

    Binary last (#990), then the phase's own report
    (``artifacts/output/<phase-id>.md``), then any markdown, then the remaining
    text. A verify phase that wrote ``fitness-ci.log`` before ``verify.md``
    used to hand the next phase a pytest log as its input (exec-269d15483078):
    disk order is not a statement about which file is the report.
    """
    return (
        isinstance(content, bytes),
        source_path != f"{_OUTPUT_DIR_REL}/{phase_id}{_MARKDOWN}",
        not source_path.endswith(_MARKDOWN),
    )
