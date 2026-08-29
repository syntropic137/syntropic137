"""What a phase actually receives from the phase before it (#988).

A phase can write many files to `artifacts/output/`. These tests drive the REAL
`ArtifactCollector` - collection and injection, both halves - and assert what
lands in the next phase's workspace.

Written to characterise current behaviour, not to bless it. The lossy cases
assert what happens TODAY and say so in their names and failure messages, so
that fixing #988 makes them fail loudly and the fixer updates them.

They are deliberately NOT xfail. `fitness-exceptions.toml` counts xfail as a
disarmed guard - "an xfail on a correctness invariant is a disabled alarm, not
a known issue" - and multi-file handoff is a correctness invariant. A test that
passes while the behaviour is wrong is the failure mode this repo already
decided against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

PHASE = "phase-1"

#: What a realistic structured phase emits: a human deliverable, machine-readable
#: findings, and per-item detail. Exactly the shape the SLP review workflow uses.
PHASE_ONE_OUTPUT: list[tuple[str, bytes]] = [
    ("artifacts/output/deliverable.md", b"# Review\nhuman-readable summary"),
    ("artifacts/output/review.yaml", b"findings:\n  - id: f1\n    severity: high"),
    ("artifacts/output/raw-findings/f1.yaml", b"id: f1\ndetail: the long version"),
]


class _Workspace:
    """Records what was injected; replays a fixed collection."""

    def __init__(self, to_collect: Sequence[tuple[str, bytes]]) -> None:
        self._to_collect = list(to_collect)
        self.injected: list[tuple[str, bytes]] = []

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        self.injected.extend(files)

    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
        assert patterns == ["artifacts/output/**/*"]
        return list(self._to_collect)


class _Repo:
    def __init__(self) -> None:
        self.saved: list[str] = []

    async def save(self, aggregate: object) -> None:
        self.saved.append(str(aggregate))


async def _run_handoff(outputs: Sequence[tuple[str, bytes]]) -> _Workspace:
    """Phase 1 emits `outputs`; return the workspace phase 2 starts from."""
    collector = ArtifactCollector(repository=_Repo(), content_storage=None, query_service=None)

    produced: list[tuple[str, str]] = []

    async def _create_artifact(**kw: object) -> None:
        produced.append((str(kw["title"]), str(kw["content"])))

    collector.create_artifact = _create_artifact  # type: ignore[method-assign,assignment]

    phase_one_ws = _Workspace(outputs)
    collected = await collector.collect_from_workspace(
        workspace=phase_one_ws,
        workflow_id="wf",
        phase_id=PHASE,
        execution_id="exec-1",
        session_id="sess-1",
        phase_name="Phase One",
        output_artifact_type="markdown",
    )

    phase_two_ws = _Workspace([])
    await collector.inject_from_previous_phases_explicit(
        workspace=phase_two_ws,
        completed_phase_ids=[PHASE],
        phase_outputs={PHASE: collected.first_content or ""},
        execution_id="exec-1",
    )
    return phase_two_ws


class TestWhatSurvivesTheHandoff:
    async def test_a_single_output_reaches_the_next_phase(self) -> None:
        """The baseline. Without this the failures below could mean the whole
        handoff is broken rather than specifically lossy."""
        ws = await _run_handoff([PHASE_ONE_OUTPUT[0]])
        assert len(ws.injected) == 1
        assert PHASE_ONE_OUTPUT[0][1] in ws.injected[0][1]

    async def test_the_original_filename_is_not_preserved(self) -> None:
        """Characterises the rename. A phase told to read `deliverable.md` will
        not find it - the content arrives as `artifacts/input/<phase-id>.md`."""
        ws = await _run_handoff([PHASE_ONE_OUTPUT[0]])
        names = [p for p, _ in ws.injected]
        assert names == [f"artifacts/input/{PHASE}.md"]
        assert not any("deliverable" in n for n in names)

    async def test_TODAY_only_one_of_three_output_files_survives(self) -> None:
        """CHARACTERISATION, not approval. #988 tracks the fix.

        Deliberately NOT xfail. This repo counts xfail as a disarmed guard - an
        xfail on a correctness invariant is a disabled alarm - and this is a
        correctness invariant. So the current behaviour is asserted exactly,
        and when #988 lands this test FAILS and whoever fixes it updates the
        number. A loud failure at the moment of the fix is the signal we want;
        a silently-passing xfail is not.
        """
        ws = await _run_handoff(PHASE_ONE_OUTPUT)
        assert len(ws.injected) == 1, (
            f"phase 2 received {len(ws.injected)} of {len(PHASE_ONE_OUTPUT)} files. "
            "If this is now 3, #988 is FIXED - update this test to assert the "
            "full contract and delete this message."
        )

    async def test_TODAY_the_surviving_file_loses_its_original_path(self) -> None:
        """The second half of #988: the survivor is renamed.

        A phase told to read `review.yaml` finds `artifacts/input/phase-1.md`
        instead, so even the one file that arrives is not where the author said
        it would be.
        """
        ws = await _run_handoff(PHASE_ONE_OUTPUT)
        paths = [p for p, _ in ws.injected]
        assert paths == [f"artifacts/input/{PHASE}.md"], (
            f"got {paths}. If original relative paths are preserved, #988 is "
            "FIXED - assert the real contract instead."
        )
        assert not any("deliverable" in p or "review.yaml" in p for p in paths)


class TestWhichFileSurvivesIsNotAuthorControlled:
    """The surviving file is whichever `collect_files` returns first, so the
    same workflow can hand a different file to phase 2 on different runs."""

    async def test_the_survivor_follows_collection_order_not_intent(self) -> None:
        forward = await _run_handoff(PHASE_ONE_OUTPUT)
        reversed_ = await _run_handoff(list(reversed(PHASE_ONE_OUTPUT)))

        assert forward.injected[0][1] != reversed_.injected[0][1], (
            "expected the surviving content to change with collection order"
        )
        assert PHASE_ONE_OUTPUT[0][1] in forward.injected[0][1]
        assert PHASE_ONE_OUTPUT[-1][1] in reversed_.injected[0][1]
