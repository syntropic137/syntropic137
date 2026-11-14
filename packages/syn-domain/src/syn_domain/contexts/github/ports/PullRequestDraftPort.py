"""PullRequestDraftPort - is a pull request still a draft, asked of GitHub live (#2058).

A ``check_run`` payload names its pull requests by number, head and base only,
so whether the PR is a draft has to be looked up. The trigger evaluator asks
before a ``check_run`` rule fires, because a draft PR is still owned by the
workflow that opened it, and a second agent on that branch is the hazard.

The port is total: a failed lookup is ``UNKNOWN`` with the reason, never an
exception, so no adapter error type crosses into the domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PullRequestReadiness(StrEnum):
    """What GitHub says about a pull request's draft flag."""

    DRAFT = "draft"
    READY = "ready"
    UNKNOWN = "unknown"
    """The lookup failed; ``PullRequestDraftReading.detail`` says why."""


@dataclass(frozen=True, slots=True)
class PullRequestDraftReading:
    """One answer to "is PR #n of this repository a draft"."""

    readiness: PullRequestReadiness
    detail: str = ""
    """Why the readiness is ``UNKNOWN``; empty otherwise."""


class PullRequestDraftPort(Protocol):
    """Port: reads a pull request's draft flag from GitHub."""

    async def read_draft_state(
        self,
        repository: str,
        pr_number: int,
        installation_id: str,
    ) -> PullRequestDraftReading:
        """Read whether PR ``pr_number`` of ``repository`` ("owner/name") is a draft.

        ``installation_id`` may be empty, in which case the adapter resolves the
        Installation from the repository. Never raises.
        """
        ...
