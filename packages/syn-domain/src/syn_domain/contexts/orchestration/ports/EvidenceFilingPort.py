"""Port for filing an evidence gate's reports as artifacts of the phase it follows (plan §A.6).

Files land at `artifacts/output/platform-evidence/<gate-id>/<name>`, owned by
phase P and never primary, so they cannot displace P's alias. The
artifact-store implementation is wired with the adapters (A.15 PR 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["EvidenceFile", "EvidenceFilingPort", "FiledEvidence"]


@dataclass(frozen=True)
class EvidenceFile:
    gate_id: str
    name: str
    content: str

    @property
    def source_path(self) -> str:
        return f"artifacts/output/platform-evidence/{self.gate_id}/{self.name}"


@dataclass(frozen=True)
class FiledEvidence:
    name: str
    source_path: str
    content: str
    artifact_id: str


class EvidenceFilingPort(Protocol):
    async def file(
        self, execution_id: str, phase_id: str, files: list[EvidenceFile]
    ) -> list[FiledEvidence]:
        """Store each file as a non-primary artifact of ``phase_id``.

        Returns the files that were stored. MUST NOT raise: a store that is
        unavailable returns fewer (or none), and a missing manifest fails
        closed downstream.
        """
        ...
