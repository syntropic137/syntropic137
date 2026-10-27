"""A direct start named by an `idempotency_key` starts once (#2129).

The key derives the execution id (`execution_id_for_key`), so every start with
it writes the same ExecutionRequest stream and the store's NoStream guard
admits exactly one. Everything here reads the request stream, the record
written before the first caller heard 200, never a projection that may not
have applied it yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from event_sourcing import StreamAlreadyExistsError
from fastapi import HTTPException

from syn_api.routes.executions.direct_start import record_execution_request
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration import (
    EvalChoice,
    EvalId,
    TagSet,
    execution_id_for_key,
    execution_request_id,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared import AdmissionTicket
    from syn_domain.contexts.orchestration import RequestExecutionCommand


class KeyedRequest(Protocol):
    """The fields of `ExecuteWorkflowRequest` a retry is compared on."""

    @property
    def idempotency_key(self) -> str | None: ...
    @property
    def inputs(self) -> dict[str, str]: ...
    @property
    def task(self) -> str | None: ...
    @property
    def repos(self) -> list[str]: ...
    @property
    def tags(self) -> TagSet: ...
    @property
    def eval_id(self) -> EvalId | None: ...
    @property
    def no_eval(self) -> bool: ...


def start_execution_id(workflow_id: str, idempotency_key: str | None) -> str:
    """A fresh id for an unkeyed start; the key's one id for a keyed start."""
    if idempotency_key is None:
        return f"exec-{uuid4().hex[:12]}"
    return execution_id_for_key(workflow_id, idempotency_key)


async def already_started(workflow_id: str, execution_id: str, request: KeyedRequest) -> bool:
    """Whether this keyed start was already accepted; 409 when its key was reused.

    A start that differs from the recorded one reused its key, and nothing
    starts. A repository that does not parse cannot have been accepted, so it
    is no replay; validation answers it.
    """
    from syn_adapters.storage.repositories import get_execution_request_repository

    recorded = await get_execution_request_repository().get_by_id(
        execution_request_id(execution_id)
    )
    if recorded is None or recorded.workflow_id is None:
        return False
    try:
        repos = [RepositoryRef.parse(r) for r in request.repos]
    except ValueError:
        return False
    if not recorded.same_request(
        workflow_id=workflow_id,
        inputs=dict(request.inputs),
        task=request.task,
        repos=repos,
        tags=request.tags,
        choice=EvalChoice(eval_id=request.eval_id, ordinary=request.no_eval),
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"idempotency_key already started execution {execution_id} "
                "with a different request; use a new key for a new start"
            ),
        )
    return True


async def record_unless_started(
    command: RequestExecutionCommand, admitted: AdmissionTicket, request: KeyedRequest
) -> bool:
    """Record the request, or True when a concurrent start with the same key won its stream.

    The loser's ticket is already given back by `record_execution_request`
    and nothing was queued, so the caller answers with the winner's
    execution instead. An unkeyed collision is not a replay and still raises.
    """
    try:
        await record_execution_request(command, admitted)
    except StreamAlreadyExistsError:
        if request.idempotency_key is None or not await already_started(
            command.workflow_id, command.execution_id, request
        ):
            raise
        return True
    return False
