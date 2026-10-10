"""Record pull request merges the GitHub event pipeline sees (Lane 2).

The "Shipped by agents" block counts PRs merged among the PRs runs created
(``GET /metrics/shipped``). Which PRs runs created is already in Lane 2 (the
``gh pr create`` tool call and its output); whether one was merged is a forge
fact, and the pipeline's ``pull_request`` events are the only place it
arrives. Nothing kept it: the pipeline holds dedup keys and fired triggers,
never the PR (#1852). This observer writes one ``github_pull_request_merged``
observation per merge, timed at ``merged_at`` so it lands on the UTC day the
merge happened.

WHICH EVENTS: ``pull_request`` with action ``closed`` and the PR merged
(``merged: true`` or a ``merged_at``), from both sources that feed the
pipeline: webhooks and the Events API poller. Like every pipeline observer it
never sees a deduplicated event or a cold-start replay (ADR-060 s9), so a merge
the pipeline never delivered live is not recorded; nothing is backfilled.

Every merge is recorded, run's or not: "was it a run's PR" is a read-time join
against the PRs runs created, so the decision can change without a rewrite.
Best-effort: a failure is logged and the merge is not recorded, never raised
into the pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from syn_shared.events import GITHUB_PULL_REQUEST_MERGED

if TYPE_CHECKING:
    from syn_domain.contexts.github import NormalizedEvent

logger = logging.getLogger(__name__)

_PULL_REQUEST = "pull_request"
_CLOSED = "closed"


@dataclass(frozen=True)
class PullRequestMerge:
    """The merge one ``pull_request`` event reports."""

    repository: str
    number: int
    merged_at: datetime
    html_url: str
    head_ref: str

    @classmethod
    def from_event(cls, event: NormalizedEvent) -> PullRequestMerge | None:
        """The merge in ``event``, or None when it does not report one."""
        if event.event_type != _PULL_REQUEST or event.action != _CLOSED:
            return None
        number = _merged_number(event)
        if number is None:
            return None
        pr = event.payload.get("pull_request") or {}
        head = pr.get("head")
        return cls(
            repository=event.repository,
            number=number,
            merged_at=_merged_at(event),
            html_url=str(pr.get("html_url") or ""),
            head_ref=str(head.get("ref") or "") if isinstance(head, dict) else "",
        )


def _merged_number(event: NormalizedEvent) -> int | None:
    """The PR number when the event's PR was merged in a named repo, else None."""
    pr = event.payload.get("pull_request") or {}
    if not (pr.get("merged") is True or pr.get("merged_at")) or not event.repository:
        return None
    number = event.payload.get("number") or pr.get("number")
    return number if isinstance(number, int) and number > 0 else None


def _merged_at(event: NormalizedEvent) -> datetime:
    """``merged_at`` as an instant; when it is missing or unreadable, receipt."""
    raw = (event.payload.get("pull_request") or {}).get("merged_at")
    if not raw:
        return event.received_at
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return event.received_at


async def record_pull_request_merge(event: NormalizedEvent) -> None:
    """Pipeline observer: write the merge ``event`` reports, if it reports one."""
    merge = PullRequestMerge.from_event(event)
    if merge is None:
        return
    from syn_api._wiring import get_event_store_instance

    store = get_event_store_instance()
    await store.initialize()
    await store.insert_one(
        {
            "event_type": GITHUB_PULL_REQUEST_MERGED,
            "time": merge.merged_at,
            "session_id": f"github_pr:{merge.repository}#{merge.number}",
            "data": {
                "repository": merge.repository,
                "number": merge.number,
                "merged_at": merge.merged_at.isoformat(),
                "html_url": merge.html_url,
                "head_ref": merge.head_ref,
                "source": event.source.value,
            },
        }
    )
    logger.info("Recorded PR merge %s#%d", merge.repository, merge.number)


_registered: set[int] = set()


def register_pull_request_merge_recorder() -> None:
    """Attach the recorder to the pipeline singleton, once per pipeline.

    Never raises: a pipeline that cannot be built here only means merges are
    not counted, which must not stop the API from starting.
    """
    from syn_api._wiring import get_event_pipeline

    try:
        pipeline = get_event_pipeline()
    except Exception:
        logger.warning("PR merge recorder not registered; merges will not be counted.")
        return
    if id(pipeline) in _registered:
        return
    pipeline.add_observer(record_pull_request_merge)
    _registered.add(id(pipeline))
