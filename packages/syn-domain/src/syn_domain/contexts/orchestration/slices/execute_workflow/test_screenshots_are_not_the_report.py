"""A screenshot is evidence for a report, never the report itself.

THE INCIDENT (exec-8fb041217a15, v0.33.2-beta.12). Since #1648 a `verify`
phase screenshots UI changes into `artifacts/output/` BEFORE it writes its
report. The codex verify stream stopped after 65 lines with no
`turn.completed`, having written two PNGs and no `verify.md`. Two places then
treated "some file exists under artifacts/output/" as "the phase delivered":

1. `AgentExecutionHandler._produced_deliverable` (#1111) completed the broken
   codex stream because the PNGs were non-empty, so the phase was marked
   completed instead of failed.
2. `ArtifactCollector._deliverables` (#1300) salvages the agent's last message
   only when NO collectable file exists, so the PNGs also switched the salvage
   off. `fix` received `artifacts/input/verify/` holding two PNGs, no
   `verify.md` and no flat `artifacts/input/verify.md`, and correctly refused.

The rule both now follow is the one `primary_text` already states: a binary
file reaches the next phase through the tree at its own path, and the phase's
TEXT is what stands for its output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts.artifacts import UNREPORTED_AGENT
from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import StorageResult
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.artifact_recovery import (
    RECOVERED_SOURCE_PATH,
    RECOVERED_TITLE_MARKER,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
    CollectedArtifacts,
    UnfinishedPhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )

pytestmark = pytest.mark.unit

#: A real PNG signature followed by an IHDR chunk header, so `ContentType.of`
#: judges it by its bytes exactly as it judged the incident's screenshots.
_PNG_DESKTOP = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x05\x00desktop"
_PNG_MOBILE = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x86mobile"

#: The incident's two collected paths, verbatim.
_DESKTOP = "artifacts/output/orchestrator-desktop-1280x800.png"
_MOBILE = "artifacts/output/orchestrator-mobile-390x844.png"
_SCREENSHOTS: list[tuple[str, bytes]] = [(_DESKTOP, _PNG_DESKTOP), (_MOBILE, _PNG_MOBILE)]

#: A final message that is a usable conclusion, unlike anything on disk, so
#: content carrying it can only have arrived by the transcript route.
SAID = (
    "VERDICT: CERTIFIED. The landing page change renders correctly at both "
    "viewports and the control-plane spec passes."
)


@dataclass
class _Workspace:
    collected_files: list[tuple[str, bytes]] = field(default_factory=list)
    injected: list[tuple[str, bytes]] = field(default_factory=list)

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        self.injected.extend(files)

    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
        return self.collected_files


@dataclass
class _Repo:
    saved: list[ArtifactAggregate] = field(default_factory=list)

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, artifact_id: str) -> None:
        return None


@dataclass
class _ObjectStore:
    """Binary content must live in object storage (#990); keep it in a dict."""

    objects: dict[str, bytes] = field(default_factory=dict)

    async def upload(self, artifact_id: str, content: bytes, **_: object) -> StorageResult:
        self.objects[artifact_id] = content
        return StorageResult(
            storage_uri=f"mem://{artifact_id}", content_hash="0" * 64, size_bytes=len(content)
        )


def _collector(repo: _Repo) -> ArtifactCollector:
    return ArtifactCollector(repo, _ObjectStore(), None)  # type: ignore[arg-type]


async def _collect(
    repo: _Repo, files: list[tuple[str, bytes]], *, said: str | None
) -> CollectedArtifacts:
    return await _collector(repo).collect_from_workspace(
        workspace=_Workspace(collected_files=files),  # type: ignore[arg-type]
        workflow_id="sdlc-implement-v3",
        phase_id="verify",
        execution_id="exec-8fb041217a15",
        session_id="s1",
        phase_name="Verify the change independently",
        output_artifact_types=("markdown",),
        agent=UNREPORTED_AGENT,
        last_agent_message=said,
    )


async def _inject_into_next_phase(result: CollectedArtifacts) -> dict[str, bytes]:
    """What `fix` finds under artifacts/input/ after `verify` produced `result`."""
    next_phase = _Workspace()
    await ArtifactCollector(_Repo(), None, None).inject_from_previous_phases_explicit(  # type: ignore[arg-type]
        workspace=next_phase,  # type: ignore[arg-type]
        completed_phase_ids=["verify"],
        phase_outputs={"verify": result.first_content} if result.first_content else {},
        execution_id="exec-8fb041217a15",
        phase_files={"verify": result.files},
    )
    return dict(next_phase.injected)


class TestAReportIsCollectedAlongsideScreenshots:
    """The collection half: PNGs on disk must not switch the salvage off."""

    @pytest.mark.asyncio
    async def test_screenshots_and_a_final_message_yield_both(self) -> None:
        repo = _Repo()

        result = await _collect(repo, list(_SCREENSHOTS), said=SAID)

        by_path = {a.source_path: a for a in repo.saved}
        assert set(by_path) == {RECOVERED_SOURCE_PATH, _DESKTOP, _MOBILE}, (
            f"both screenshots AND the report must be stored, got {sorted(by_path)}"
        )
        report = by_path[RECOVERED_SOURCE_PATH]
        assert SAID in report.content
        assert RECOVERED_TITLE_MARKER in (report.title or "")
        assert report.is_primary_deliverable, "the report, not a screenshot, is the primary"
        assert not by_path[_DESKTOP].is_primary_deliverable
        assert not by_path[_MOBILE].is_primary_deliverable
        assert result.first_content is not None and SAID in result.first_content
        assert result.deliverable_recovered

    @pytest.mark.asyncio
    async def test_the_next_phase_receives_the_report_and_the_screenshots(self) -> None:
        result = await _collect(_Repo(), list(_SCREENSHOTS), said=SAID)

        injected = await _inject_into_next_phase(result)

        assert "artifacts/input/verify.md" in injected, (
            f"fix must find the flat report alias, got {sorted(injected)}"
        )
        assert SAID.encode() in injected["artifacts/input/verify.md"]
        assert SAID.encode() in injected["artifacts/input/verify/recovered-from-transcript.md"]
        assert injected["artifacts/input/verify/orchestrator-desktop-1280x800.png"] == _PNG_DESKTOP
        assert injected["artifacts/input/verify/orchestrator-mobile-390x844.png"] == _PNG_MOBILE

    @pytest.mark.asyncio
    async def test_a_written_report_is_never_replaced_by_the_transcript(self) -> None:
        """Regression guard: a phase that wrote verify.md is stored exactly as written."""
        repo = _Repo()
        written = b"# Verify\n\nVERDICT: BLOCKED on the mobile layout."

        await _collect(repo, [*_SCREENSHOTS, ("artifacts/output/verify.md", written)], said=SAID)

        paths = [a.source_path for a in repo.saved]
        assert RECOVERED_SOURCE_PATH not in paths
        assert paths[0] == "artifacts/output/verify.md"
        assert repo.saved[0].is_primary_deliverable
        assert all(SAID not in a.content for a in repo.saved if isinstance(a.content, str))

    @pytest.mark.asyncio
    async def test_a_failed_phase_with_screenshots_keeps_its_report_too(self) -> None:
        """The unfinished-phase route had the same `nothing stored` gate."""
        repo = _Repo()

        await _collector(repo).collect_from_unfinished_phase(
            workspace=_Workspace(collected_files=list(_SCREENSHOTS)),  # type: ignore[arg-type]
            workflow_id="sdlc-implement-v3",
            phase_id="verify",
            execution_id="exec-8fb041217a15",
            session_id="s1",
            phase_name="Verify the change independently",
            output_artifact_types=("markdown",),
            agent=UNREPORTED_AGENT,
            outcome=UnfinishedPhase.FAILED,
            last_agent_message=SAID,
        )

        by_path = {a.source_path: a for a in repo.saved}
        assert set(by_path) == {RECOVERED_SOURCE_PATH, _DESKTOP, _MOBILE}
        assert by_path[RECOVERED_SOURCE_PATH].is_primary_deliverable
        assert [a for a in repo.saved if a.is_primary_deliverable] == [
            by_path[RECOVERED_SOURCE_PATH]
        ], "exactly one primary, and it is the text"


async def _broken_codex_stream_exit_code(files: list[tuple[str, bytes]]) -> int | None:
    """The exit code a codex phase gets when its stream stopped before turn.completed."""
    workspace = MagicMock()
    workspace.last_stream_exit_code = 0
    workspace.collect_files = AsyncMock(return_value=files)
    stream_result = StreamResult(
        line_count=65,
        interrupt_requested=False,
        interrupt_reason=None,
        error_reason=MISSING_TERMINAL_TURN_REASON,
    )
    with patch(
        "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.CodexStreamProcessor"
    ) as processor:
        processor.return_value.process_stream = AsyncMock(return_value=stream_result)
        result = await AgentExecutionHandler(controller=None).handle(
            todo=TodoItem(
                execution_id="exec-8fb041217a15", action=TodoAction.RUN_AGENT, phase_id="verify"
            ),
            workspace=workspace,
            agent_env={},
            claude_cmd=["codex", "exec", "--json", "verify"],
            session_id="s1",
            agent_model="gpt-sol",
            timeout_seconds=3600,
            collector=AsyncMock(),
            runner="codex",
        )
    return result.command.exit_code


class TestScreenshotsDoNotCompleteABrokenCodexStream:
    """The completion half: #1111's exception needs a REPORT, not any file."""

    @pytest.mark.anyio
    async def test_the_incident_shape_fails_the_phase(self) -> None:
        assert await _broken_codex_stream_exit_code(list(_SCREENSHOTS)) == 1

    @pytest.mark.anyio
    async def test_screenshots_beside_a_written_report_still_complete(self) -> None:
        files = [*_SCREENSHOTS, ("artifacts/output/verify.md", b"## Verdict\nCERTIFIED")]
        assert await _broken_codex_stream_exit_code(files) == 0
