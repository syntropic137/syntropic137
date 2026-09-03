"""Which pull request an execution reviewed, read from its inputs (#1097).

A review execution names its subject the same way every other execution names
its repositories: through the ``inputs`` recorded on WorkflowExecutionStarted.
There is no second, structured carrier for it, so this is the whole of what the
publisher can know without asking an external service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts._shared.repository_ref import RepositoryRef

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewTarget:
    """The pull request a review execution judged."""

    repository: str
    """Full repository name, ``owner/repo``."""

    pr_number: int
    """Pull request number."""


def review_target_from_inputs(inputs: Mapping[str, object]) -> ReviewTarget | None:
    """Read the reviewed pull request from execution inputs, or None.

    None means this execution did not name a pull request, so there is nothing
    to publish to. That is the ordinary case for most workflows and is not an
    error.
    """
    pr_number = _pr_number(inputs.get("pr_number"))
    if pr_number is None:
        return None

    repository = _repository(inputs)
    if repository is None:
        logger.warning(
            "Execution names pr_number=%s but no single repository; cannot publish a verdict",
            pr_number,
        )
        return None

    return ReviewTarget(repository=repository, pr_number=pr_number)


def _pr_number(value: object) -> int | None:
    """Coerce an inputs value to a positive PR number, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number > 0 else None


def _repository(inputs: Mapping[str, object]) -> str | None:
    """Resolve ``owner/repo`` from an explicit slug, else from a sole ``repos`` entry.

    ``repos`` is the CSV of clone URLs every repo-bearing execution carries
    (ADR-058). With more than one entry the pull request number is ambiguous,
    so nothing is resolved.
    """
    explicit = inputs.get("repository")
    if isinstance(explicit, str) and explicit:
        return _parse(explicit)

    repos = inputs.get("repos")
    if not isinstance(repos, str):
        return None
    entries = [part.strip() for part in repos.split(",") if part.strip()]
    return _parse(entries[0]) if len(entries) == 1 else None


def _parse(value: str) -> str | None:
    try:
        return RepositoryRef.parse(value).slug
    except ValueError:
        logger.warning("Cannot read a repository from '%s'", value)
        return None
