"""The quarantine notice to-do list's records, and what a notice says (#1547)."""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - runtime for Pydantic
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (  # noqa: TC001 - runtime for Pydantic
    QuarantinedRef,
)

logger = logging.getLogger(__name__)

#: `pending` is owed a post or an update; `awaiting_pr` knows no PR yet and
#: asks the forge again on every pass; `posted` is done until the facts change.
#: There is no expiry: a notice is owed until a PR exists to receive it. A
#: fresh deploy replaying old failures cannot spam PRs with it, because events
#: written before #1547 carry no `quarantined_refs`, and a rebuilt to-do list
#: finds its old comment by marker and edits it rather than posting again.
NoticeStatus = Literal["pending", "awaiting_pr", "posted"]

OWED_STATUSES: tuple[NoticeStatus, ...] = ("pending", "awaiting_pr")


class QuarantineNotice(BaseModel):
    """One (execution, phase, repository) whose quarantined work a PR is owed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    phase_id: str
    #: When the phase failed, or the save after its cancellation ran.
    failed_at: datetime
    quarantined: QuarantinedRef
    status: NoticeStatus = "pending"
    #: The PR the comment went to, once one did.
    pull_request: int | None = None
    #: The forge's id for the comment, so a retry edits it instead of adding one.
    comment_id: int | None = None

    @property
    def key(self) -> str:
        return f"{self.execution_id}:{self.phase_id}:{self.quarantined.repository}"

    @property
    def marker(self) -> str:
        """An invisible line identifying this notice in the comment body.

        The forge-side half of idempotency: a post whose `comment_id` never
        reached the store is found again by this, not posted a second time.
        """
        return f"<!-- syn-quarantine:{self.key} -->"

    def body(self) -> str:
        """What the PR is told. Refs, commits and ids only - never a token or a
        workspace path, which nothing here is given in the first place."""
        q = self.quarantined
        commit = f"`{q.commit}`" if q.commit else "(the ref's head)"
        return "\n".join(
            [
                self.marker,
                "**Unpushed work from this run was quarantined, not pushed to this branch.**",
                "",
                f"- Execution: `{self.execution_id}`",
                f"- Phase: `{self.phase_id}`",
                f"- Branch it was on: `{q.branch}`",
                f"- Ref: `{q.ref}`",
                f"- Commit: {commit} ({q.commit_count} unpushed commit(s))",
                "",
                *(["```", q.diffstat.replace("`", "'"), "```", ""] if q.diffstat else []),
                "Nothing on this PR includes it. To review or recover it:",
                "",
                "```",
                q.fetch_command,
                "```",
            ]
        )


def read_notice(row: object) -> QuarantineNotice | None:
    """A stored row as a notice, or None - logged - when it cannot be read."""
    try:
        return QuarantineNotice.model_validate(row)
    except ValidationError:
        logger.warning("Unreadable quarantine notice skipped: %r", row)
        return None
