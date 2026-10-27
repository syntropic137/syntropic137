"""ExecutionRequest value objects (#1557)."""

from __future__ import annotations

import hashlib

#: Prefixes a request's aggregate id. A request may never share its
#: execution's id: the event store keys a stream by aggregate id alone, so the
#: request would become version 1 of the execution's stream and the start's
#: NoStream write would be refused as a duplicate dispatch (see
#: `ExecutionRequestAggregate`'s module docstring).
EXECUTION_REQUEST_ID_PREFIX = "request-"


def execution_request_id(execution_id: str) -> str:
    """The aggregate id of the request that names ``execution_id``."""
    return f"{EXECUTION_REQUEST_ID_PREFIX}{execution_id}"


def execution_id_for_key(workflow_id: str, idempotency_key: str) -> str:
    """The one execution id a keyed start of ``workflow_id`` gets, on every call and host (#2129).

    Two starts with the same key derive the same id, so they write the same
    request stream and its NoStream guard admits exactly one; the other finds
    the winner. Scoped by workflow, so one key on two workflows is two starts.
    Same shape as a minted id (``exec-`` and 12 hex).
    """
    if not idempotency_key:
        raise ValueError("an idempotency key must not be empty")
    digest = hashlib.sha256(f"{workflow_id}\0{idempotency_key}".encode()).hexdigest()
    return f"exec-{digest[:12]}"
