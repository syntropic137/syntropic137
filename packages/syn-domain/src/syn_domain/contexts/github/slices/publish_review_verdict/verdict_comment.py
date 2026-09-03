"""Rendering and recognising a review-verdict comment (#1097).

A verdict comment carries a machine-readable marker as its first line:

    <!-- syn137:review-verdict execution=exec-32ea5ed0 head=9d5908a6 -->

The marker is what makes the comment idempotent and what makes staleness
visible: re-running the review on the same execution finds its own marker and
posts nothing, while a review of a NEW head finds the previous marker and says
which verdict it supersedes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Longest body GitHub accepts on an issue comment. A verdict past this is
#: truncated rather than dropped -- a rejected POST would lose it entirely.
MAX_COMMENT_LENGTH = 65536

_MARKER_RE = re.compile(
    r"<!--\s*syn137:review-verdict\s+execution=(?P<execution>\S+)\s+head=(?P<head>\S+)\s*-->"
)


@dataclass(frozen=True, slots=True)
class VerdictMarker:
    """Identifies the run a verdict comment came from."""

    execution_id: str
    head_sha: str

    def render(self) -> str:
        """The HTML comment GitHub renders invisibly and ``find`` reads back."""
        return f"<!-- syn137:review-verdict execution={self.execution_id} head={self.head_sha} -->"

    @property
    def short_head(self) -> str:
        """First 8 characters of the head SHA, as GitHub abbreviates it."""
        return self.head_sha[:8]


def find_markers(comment_bodies: list[str]) -> list[VerdictMarker]:
    """Extract the verdict marker from each comment that carries one.

    Comments without a marker -- human replies, the trigger-started notice --
    are skipped. Order is preserved, so the last entry is the most recent
    verdict on that pull request.
    """
    markers: list[VerdictMarker] = []
    for body in comment_bodies:
        match = _MARKER_RE.search(body)
        if match is not None:
            markers.append(VerdictMarker(execution_id=match["execution"], head_sha=match["head"]))
    return markers


def render_verdict_comment(
    marker: VerdictMarker,
    verdict: str,
    supersedes: VerdictMarker | None,
    artifact_id: str,
) -> str:
    """Compose the comment body for one verdict.

    Args:
        marker: Identifies this run; rendered first so ``find_markers`` sees it.
        verdict: The report phase's deliverable, verbatim.
        supersedes: The most recent earlier verdict on this pull request, if
            any. Named in the header so a stacked re-review is self-describing
            rather than silently duplicated.
        artifact_id: Where the untruncated verdict lives.
    """
    header = [
        marker.render(),
        f"## Review verdict — head `{marker.short_head}`",
        "",
    ]
    if supersedes is not None:
        header.append(
            f"Re-review. Supersedes the verdict for head `{supersedes.short_head}` "
            f"from execution `{supersedes.execution_id}`."
        )
        header.append("")
    header.append(f"<sub>Execution `{marker.execution_id}` · artifact `{artifact_id}`</sub>")
    header.append("")

    prefix = "\n".join(header)
    budget = MAX_COMMENT_LENGTH - len(prefix)
    return prefix + _fit(verdict, budget, artifact_id)


def _fit(verdict: str, budget: int, artifact_id: str) -> str:
    """Return ``verdict`` unchanged, or truncated with a pointer to the artifact."""
    if len(verdict) <= budget:
        return verdict
    notice = f"\n\n---\n\n_Truncated. Full verdict in artifact `{artifact_id}`._"
    return verdict[: budget - len(notice)] + notice
