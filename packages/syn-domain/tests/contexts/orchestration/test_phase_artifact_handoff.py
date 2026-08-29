"""What a phase actually receives from the phase before it (#988).

A phase outputs a DIRECTORY, not a file. These tests drive the REAL
`ArtifactCollector` - collection and injection, both halves - and assert what
lands in the next phase's workspace.

They were originally written to CHARACTERISE the bug: only one arbitrary file
per phase survived, flattened to `artifacts/input/<phase-id>.md`. Three of them
asserted that lossy behaviour exactly, deliberately NOT as xfail, so that fixing
#988 would turn them red and force this update. It did. They now assert the real
contract: every file, at its original relative path, under its phase's id.

Deliberately still NOT xfail. `fitness-exceptions.toml` counts xfail as a
disarmed guard - "an xfail on a correctness invariant is a disabled alarm, not
a known issue" - and multi-file handoff is a correctness invariant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.artifacts import PhaseOutputFile
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
        phase_files={PHASE: collected.files},
    )
    return phase_two_ws


class TestWhatSurvivesTheHandoff:
    async def test_a_single_output_reaches_the_next_phase(self) -> None:
        """The baseline. Without this the failures below could mean the whole
        handoff is broken rather than specifically lossy."""
        ws = await _run_handoff([PHASE_ONE_OUTPUT[0]])
        assert PHASE_ONE_OUTPUT[0][1] in [body for _, body in ws.injected]

    async def test_the_original_filename_is_preserved(self) -> None:
        """Was `test_the_original_filename_is_NOT_preserved`.

        A phase told to read `deliverable.md` must find `deliverable.md`, under
        the producing phase's id. The flat alias is still written beside it.
        """
        ws = await _run_handoff([PHASE_ONE_OUTPUT[0]])
        names = [p for p, _ in ws.injected]
        assert f"artifacts/input/{PHASE}/deliverable.md" in names
        # The pre-#988 flat name survives one release as an alias.
        assert f"artifacts/input/{PHASE}.md" in names

    async def test_every_output_file_survives(self) -> None:
        """Was `test_TODAY_only_one_of_three_output_files_survives`.

        Its failure message said: "If this is now 3, #988 is FIXED - update this
        test to assert the full contract." It is now 3, and this is that update.
        """
        ws = await _run_handoff(PHASE_ONE_OUTPUT)
        tree = {p: b for p, b in ws.injected if p.startswith(f"artifacts/input/{PHASE}/")}
        assert len(tree) == len(PHASE_ONE_OUTPUT), (
            f"phase 2 received {len(tree)} of {len(PHASE_ONE_OUTPUT)} files: {sorted(tree)}"
        )
        assert set(tree.values()) == {body for _, body in PHASE_ONE_OUTPUT}

    async def test_each_file_keeps_its_original_relative_path(self) -> None:
        """Was `test_TODAY_the_surviving_file_loses_its_original_path`.

        Every file lands at its path under `artifacts/output/`, re-rooted at
        `artifacts/input/<phase-id>/`. Nested directories are preserved, so a
        phase told to read `raw-findings/f1.yaml` finds it there.
        """
        ws = await _run_handoff(PHASE_ONE_OUTPUT)
        by_path = dict(ws.injected)
        assert by_path[f"artifacts/input/{PHASE}/deliverable.md"] == PHASE_ONE_OUTPUT[0][1]
        assert by_path[f"artifacts/input/{PHASE}/review.yaml"] == PHASE_ONE_OUTPUT[1][1]
        assert by_path[f"artifacts/input/{PHASE}/raw-findings/f1.yaml"] == PHASE_ONE_OUTPUT[2][1]

    async def test_the_flat_alias_is_still_written(self) -> None:
        """Kept for ONE release so workflows reading the old path keep working.

        Asserted rather than assumed: an alias nobody tests is an alias that
        silently stops being written.
        """
        ws = await _run_handoff(PHASE_ONE_OUTPUT)
        by_path = dict(ws.injected)
        assert by_path[f"artifacts/input/{PHASE}.md"] == PHASE_ONE_OUTPUT[0][1]


class TestOrderNoLongerDecidesWhatTheNextPhaseSees:
    """Was `TestWhichFileSurvivesIsNotAuthorControlled`.

    The old defect: the survivor was whichever `collect_files` returned first,
    so the same workflow could hand a different file to phase 2 on different
    runs. Now every file survives, so collection order cannot change the tree.
    """

    async def test_collection_order_does_not_change_the_injected_tree(self) -> None:
        forward = await _run_handoff(PHASE_ONE_OUTPUT)
        reversed_ = await _run_handoff(list(reversed(PHASE_ONE_OUTPUT)))

        def tree(ws: _Workspace) -> dict[str, bytes]:
            return {p: b for p, b in ws.injected if p.startswith(f"artifacts/input/{PHASE}/")}

        assert tree(forward) == tree(reversed_)
        assert len(tree(forward)) == len(PHASE_ONE_OUTPUT)


class TestPreV5ArtifactsFallBackToTheFlatName:
    """Artifacts created before ArtifactCreated v5 carry no `source_path`.

    Their original path was never recorded and cannot be recovered, so they get
    the flat alias and no invented tree path. This is the compatibility path
    for artifacts already in the event store; it is asserted, not assumed.
    """

    async def _inject(self, files: list[PhaseOutputFile]) -> _Workspace:
        collector = ArtifactCollector(repository=_Repo(), content_storage=None, query_service=None)
        ws = _Workspace([])
        await collector.inject_from_previous_phases_explicit(
            workspace=ws,
            completed_phase_ids=[PHASE],
            phase_outputs={PHASE: "legacy content"},
            execution_id="exec-1",
            phase_files={PHASE: files},
        )
        return ws

    async def test_a_file_without_a_source_path_gets_the_flat_name_only(self) -> None:
        ws = await self._inject([PhaseOutputFile(source_path=None, content="legacy content")])
        assert ws.injected == [(f"artifacts/input/{PHASE}.md", b"legacy content")]

    async def test_no_tree_path_is_invented_for_it(self) -> None:
        ws = await self._inject([PhaseOutputFile(source_path=None, content="legacy content")])
        assert not any(p.startswith(f"artifacts/input/{PHASE}/") for p, _ in ws.injected)

    async def test_a_mixed_phase_keeps_the_paths_it_does_have(self) -> None:
        """A phase whose artifacts straddle the v5 boundary must not lose the
        ones that DO carry a path just because a sibling does not."""
        ws = await self._inject(
            [
                PhaseOutputFile(source_path=None, content="legacy content"),
                PhaseOutputFile(source_path="artifacts/output/review.yaml", content="findings: []"),
            ]
        )
        by_path = dict(ws.injected)
        assert by_path[f"artifacts/input/{PHASE}/review.yaml"] == b"findings: []"
        assert by_path[f"artifacts/input/{PHASE}.md"] == b"legacy content"


class TestVisibilityAcrossMultiplePreviousPhases:
    """The other axis. #988 is about files-per-phase; this is phases-per-phase.

    Stated intent: a phase should see the outputs of the phases before it -
    ideally ALL of them, at minimum the immediately preceding one. This half
    already worked before #988 and must keep working after it.
    """

    async def _run_multi(
        self,
        phases: list[str],
        phase_files: dict[str, list[PhaseOutputFile]] | None = None,
    ) -> _Workspace:
        collector = ArtifactCollector(repository=_Repo(), content_storage=None, query_service=None)
        ws = _Workspace([])
        await collector.inject_from_previous_phases_explicit(
            workspace=ws,
            completed_phase_ids=phases,
            phase_outputs={p: f"output of {p}" for p in phases},
            execution_id="exec-1",
            phase_files=phase_files or {},
        )
        return ws

    async def test_a_later_phase_sees_EVERY_earlier_phase(self) -> None:
        ws = await self._run_multi(["phase-1", "phase-2"])
        paths = sorted(p for p, _ in ws.injected)
        assert paths == ["artifacts/input/phase-1.md", "artifacts/input/phase-2.md"], (
            f"a later phase did not see every earlier phase: {paths}"
        )

    async def test_each_earlier_phase_keeps_its_own_content(self) -> None:
        """Accumulation is worthless if the contents collide or overwrite."""
        ws = await self._run_multi(["phase-1", "phase-2"])
        by_path = {p: b.decode() for p, b in ws.injected}
        assert by_path["artifacts/input/phase-1.md"] == "output of phase-1"
        assert by_path["artifacts/input/phase-2.md"] == "output of phase-2"

    async def test_the_minimum_bar_holds_the_immediately_previous_phase_arrives(
        self,
    ) -> None:
        """The floor the intent names explicitly."""
        ws = await self._run_multi(["phase-1"])
        assert [p for p, _ in ws.injected] == ["artifacts/input/phase-1.md"]

    async def test_two_phases_emitting_the_SAME_filename_do_not_collide(self) -> None:
        """The phase id namespaces each tree. Without it, phase 2's
        `deliverable.md` would silently overwrite phase 1's."""
        ws = await self._run_multi(
            ["phase-1", "phase-2"],
            {
                "phase-1": [
                    PhaseOutputFile(
                        source_path="artifacts/output/deliverable.md", content="from one"
                    )
                ],
                "phase-2": [
                    PhaseOutputFile(
                        source_path="artifacts/output/deliverable.md", content="from two"
                    )
                ],
            },
        )
        by_path = {p: b.decode() for p, b in ws.injected}
        assert by_path["artifacts/input/phase-1/deliverable.md"] == "from one"
        assert by_path["artifacts/input/phase-2/deliverable.md"] == "from two"


class TestTheRestartPathRebuildsTheTreeToo:
    """The processor's in-memory cache dies with the process.

    After a crash the next phase is provisioned from the projection instead, so
    that path has to rebuild the same tree. Before #988 it independently took
    "the first artifact found for each phase", which meant a restart silently
    degraded a workflow from N files to one even where the live path was fixed.
    """

    class _QueryService:
        def __init__(self, files: dict[str, list[PhaseOutputFile]]) -> None:
            self._files = files
            self.asked_for: list[list[str]] = []

        async def get_for_phase_injection(
            self,
            execution_id: str,
            completed_phase_ids: list[str],
        ) -> dict[str, str]:
            del execution_id
            return dict.fromkeys(completed_phase_ids, "primary from projection")

        async def get_files_for_phase_injection(
            self,
            execution_id: str,
            completed_phase_ids: list[str],
        ) -> dict[str, list[PhaseOutputFile]]:
            del execution_id
            self.asked_for.append(list(completed_phase_ids))
            return {pid: self._files.get(pid, []) for pid in completed_phase_ids}

    async def test_files_absent_from_the_cache_come_from_the_projection(self) -> None:
        query = self._QueryService(
            {
                PHASE: [
                    PhaseOutputFile(source_path=path, content=body.decode())
                    for path, body in PHASE_ONE_OUTPUT
                ]
            }
        )
        collector = ArtifactCollector(repository=_Repo(), content_storage=None, query_service=query)
        ws = _Workspace([])
        await collector.inject_from_previous_phases_explicit(
            workspace=ws,
            completed_phase_ids=[PHASE],
            phase_outputs={},
            execution_id="exec-1",
            phase_files={},
        )
        by_path = dict(ws.injected)
        assert query.asked_for == [[PHASE]]
        assert by_path[f"artifacts/input/{PHASE}/deliverable.md"] == PHASE_ONE_OUTPUT[0][1]
        assert by_path[f"artifacts/input/{PHASE}/review.yaml"] == PHASE_ONE_OUTPUT[1][1]
        assert by_path[f"artifacts/input/{PHASE}/raw-findings/f1.yaml"] == PHASE_ONE_OUTPUT[2][1]

    async def test_a_cached_phase_is_not_re_queried(self) -> None:
        """Only the phases actually missing are fetched; re-querying a cached
        phase would make every provision O(all artifacts) for no gain."""
        query = self._QueryService({})
        collector = ArtifactCollector(repository=_Repo(), content_storage=None, query_service=query)
        ws = _Workspace([])
        await collector.inject_from_previous_phases_explicit(
            workspace=ws,
            completed_phase_ids=[PHASE],
            phase_outputs={PHASE: "cached"},
            execution_id="exec-1",
            phase_files={
                PHASE: [PhaseOutputFile(source_path="artifacts/output/a.md", content="cached")]
            },
        )
        assert query.asked_for == []
        assert dict(ws.injected)[f"artifacts/input/{PHASE}/a.md"] == b"cached"
