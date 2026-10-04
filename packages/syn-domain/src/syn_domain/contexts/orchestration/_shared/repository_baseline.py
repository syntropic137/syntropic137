"""A repository pinned to the exact commit an eval starts from (evals plan, #967).

``RepositoryRef`` says WHICH repository; it says nothing about which state of
it. ``RepositoryBaseline`` adds the revision without touching that identity:
the ref a person asked for, kept for display, and the full commit sha it
resolved to, which is what every run actually checks out. A branch moving
later changes nothing here, which is the whole point of a baseline.

The sha is resolved BEFORE a baseline is built, through
``RevisionResolverPort``. Nothing in this module talks to git; it only refuses
a value that cannot be a full commit id, so an abbreviated sha or a branch name
mistaken for one never reaches an event.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from syn_domain.contexts._shared.repository_ref import RepositoryRef  # noqa: TC001

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
