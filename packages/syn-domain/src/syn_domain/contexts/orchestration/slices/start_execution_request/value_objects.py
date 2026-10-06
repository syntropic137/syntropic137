"""The execution request start to-do list's records (#1557)."""

from __future__ import annotations

from syn_domain.contexts.orchestration._shared.start_record import StartRecord


class ExecutionRequestStartRecord(StartRecord):
    """One admitted direct start on the to-do list, keyed by its execution id.

    The execution does not exist until its start runs, so this record is also
    what `GET /executions/{id}` answers from while it waits: it survives a
    restart, which the in-memory execution budget does not.
    """

    execution_id: str
    workflow_id: str

    @property
    def key(self) -> str:
        return self.execution_id
