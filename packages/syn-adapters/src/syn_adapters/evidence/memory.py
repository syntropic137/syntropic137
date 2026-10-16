"""Test doubles for the evidence gate's ports. Refuse to construct outside test/offline (ADR-060).

Each double is scripted: a test says what the forge answers, and the double
records what it was asked, so a test can assert the handler's order of calls
(record, then post) as well as its outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration.ports.EvidenceFilingPort import FiledEvidence
from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import (
    Accepted,
    RunConclusion,
)

if TYPE_CHECKING:
    from datetime import datetime

    from syn_domain.contexts.orchestration._shared.evidence_contract import EvidenceReport
    from syn_domain.contexts.orchestration.ports.EvidenceFilingPort import EvidenceFile
    from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import (
        DispatchResult,
        EvidenceAttemptRef,
        RunRef,
    )
    from syn_domain.contexts.orchestration.ports.RemoteBranchWriterPort import RemovalResult


@dataclass(frozen=True)
class RunScript:
    """What the forge does with one dispatch."""

    dispatch: DispatchResult
    #: The run ``find_run`` returns for it; None never becomes visible.
    found: RunRef | None = None
    conclusion: RunConclusion = RunConclusion.SUCCESS
    report: EvidenceReport | None = None
    #: The nonce the report carries. None echoes the dispatch the run answers,
    #: as the producers do; set it to play a report from another attempt.
    report_dispatch_id: str | None = None


class InMemoryEvidenceRunner(InMemoryAdapter):
    """Plays one `RunScript` per dispatch, in order."""

    def __init__(
        self, scripts: list[RunScript], check: RunConclusion = RunConclusion.SUCCESS
    ) -> None:
        super().__init__()
        self._scripts = list(scripts)
        self._by_dispatch: dict[str, RunScript] = {}
        self._by_run: dict[int, RunScript] = {}
        self._run_dispatch: dict[int, str] = {}
        self._check = check
        self.dispatched: list[EvidenceAttemptRef] = []
        self.checked: list[tuple[str, str, str]] = []

    async def dispatch(self, attempt: EvidenceAttemptRef) -> DispatchResult:
        self.dispatched.append(attempt)
        script = self._scripts.pop(0)
        self._by_dispatch[attempt.dispatch_id] = script
        for run in (
            script.found,
            script.dispatch.run if isinstance(script.dispatch, Accepted) else None,
        ):
            if run is not None:
                self._by_run[run.run_id] = script
                self._run_dispatch[run.run_id] = attempt.dispatch_id
        return script.dispatch

    async def find_run(self, attempt: EvidenceAttemptRef) -> RunRef | None:
        script = self._by_dispatch.get(attempt.dispatch_id)
        return None if script is None else script.found

    async def await_run(self, run: RunRef, not_after: datetime) -> RunConclusion:
        del not_after
        return self._by_run[run.run_id].conclusion

    async def await_check(
        self, repository: str, sha: str, check_name: str, not_after: datetime
    ) -> RunConclusion:
        del not_after
        self.checked.append((repository, sha, check_name))
        return self._check

    async def fetch_report(self, run: RunRef) -> EvidenceReport | None:
        script = self._by_run[run.run_id]
        if script.report is None:
            return None
        nonce = script.report_dispatch_id or self._run_dispatch[run.run_id]
        return script.report.model_copy(update={"dispatch_id": nonce})


class InMemoryRemoteBranchWriter(InMemoryAdapter):
    """Answers every removal with one scripted result."""

    def __init__(self, result: RemovalResult) -> None:
        super().__init__()
        self._result = result
        self.calls: list[tuple[str, str, str, tuple[str, ...]]] = []

    async def remove_paths(
        self, repository: str, branch: str, before_sha: str, paths: tuple[str, ...]
    ) -> RemovalResult:
        self.calls.append((repository, branch, before_sha, paths))
        return self._result


class InMemoryEvidenceFiling(InMemoryAdapter):
    """Stores every file it is given; ``available=False`` stores nothing (a store outage)."""

    def __init__(self, *, available: bool = True) -> None:
        super().__init__()
        self._available = available
        self.filed: list[tuple[str, FiledEvidence]] = []

    async def file(
        self, execution_id: str, phase_id: str, files: list[EvidenceFile]
    ) -> list[FiledEvidence]:
        del execution_id
        if not self._available:
            return []
        stored = [
            FiledEvidence(
                name=f.name,
                source_path=f.source_path,
                content=f.content,
                artifact_id=f"art-{len(self.filed) + i}",
            )
            for i, f in enumerate(files)
        ]
        self.filed.extend((phase_id, s) for s in stored)
        return stored
