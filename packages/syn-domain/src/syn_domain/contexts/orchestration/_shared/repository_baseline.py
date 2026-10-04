"""A repository pinned to the exact commit an eval starts from (evals plan, #967).

``RepositoryRef`` says WHICH repository; it says nothing about which state of
it. ``RepositoryBaseline`` adds the revision without touching that identity:
the ref a person asked for, kept for display, and the full commit sha it
resolved to, which is what every run actually checks out. A branch moving
later changes nothing here, which is the whole point of a baseline.

The sha is resolved BEFORE a baseline is built, through
``RevisionResolverPort`` (``resolve_baseline`` below). Nothing in this module
talks to git; it only refuses a value that cannot be a full commit id, so an
abbreviated sha or a branch name mistaken for one never reaches an event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from syn_domain.contexts._shared.repository_ref import RepositoryRef  # noqa: TC001
from syn_domain.contexts.orchestration.ports.RevisionResolverPort import ResolvedRevision

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
        RevisionResolverPort,
        UnresolvedRevision,
    )

#: A full object id: 40 hex characters (SHA-1) or 64 (SHA-256 repositories).
#: Lowercase only, so one commit has exactly one spelling.
FULL_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

#: Long enough for any real branch or tag name; git itself caps refs near here.
MAX_REQUESTED_REF_LENGTH = 255


class RepositoryBaseline(BaseModel):
    """One repository, the ref that was asked for, and the commit it resolved to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: RepositoryRef
    requested_ref: str = Field(..., min_length=1, max_length=MAX_REQUESTED_REF_LENGTH)
    commit_sha: str

    @field_validator("requested_ref")
    @classmethod
    def _ref_is_one_token(cls, value: str) -> str:
        if value != value.strip() or any(ch.isspace() for ch in value):
            msg = f"requested_ref {value!r} must not contain whitespace"
            raise ValueError(msg)
        return value

    @field_validator("commit_sha")
    @classmethod
    def _sha_is_full(cls, value: str) -> str:
        if not FULL_COMMIT_SHA.fullmatch(value):
            msg = (
                f"commit_sha {value!r} is not a full lowercase commit id "
                "(40 or 64 hex characters); resolve the ref before building a baseline"
            )
            raise ValueError(msg)
        return value


@dataclass(frozen=True)
class BaselineRequest:
    """A repository and the ref a person asked for, before it is pinned."""

    repository: RepositoryRef
    requested_ref: str


class UnresolvedBaselineError(ValueError):
    """At least one requested ref could not be pinned; nothing was recorded."""

    def __init__(self, failures: list[tuple[BaselineRequest, UnresolvedRevision]]) -> None:
        parts = [
            f"{req.repository.slug}@{req.requested_ref} ({failure.reason.value}"
            + (f": {failure.detail})" if failure.detail else ")")
            for req, failure in failures
        ]
        super().__init__("could not resolve baseline ref(s): " + ", ".join(parts))
        self.failures = failures


async def resolve_baseline(
    resolver: RevisionResolverPort,
    requests: Iterable[BaselineRequest],
) -> tuple[RepositoryBaseline, ...]:
    """Pin every request to a commit, or refuse all of them.

    All or nothing: a baseline with one repository missing is a different
    experiment, so a single unresolved ref raises ``UnresolvedBaselineError``
    naming every failure, rather than recording the ones that worked.
    """
    pinned: list[RepositoryBaseline] = []
    failures: list[tuple[BaselineRequest, UnresolvedRevision]] = []
    for req in requests:
        answer = await resolver.resolve(req.repository, req.requested_ref)
        if isinstance(answer, ResolvedRevision):
            pinned.append(
                RepositoryBaseline(
                    repository=req.repository,
                    requested_ref=req.requested_ref,
                    commit_sha=answer.commit_sha,
                )
            )
        else:
            failures.append((req, answer))
    if failures:
        raise UnresolvedBaselineError(failures)
    return tuple(pinned)
