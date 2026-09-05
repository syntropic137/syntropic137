"""A phase cannot report completed while holding work nobody can reach (#1184).

These tests run REAL git against REAL repositories. The gate is nothing but
the git commands it issues, so a workspace double returning canned stdout would
only assert the shape of the double: it would stay green if ``--not --remotes``
became ``--not --branches``, if the push became a force, or if the quarantine
commit were built from an empty tree. Every assertion below is therefore read
back out of the origin repository afterwards, not off the object the gate
returned.

The gate hardcodes ``/workspace/repos`` and ``/tmp``; the workspace double
rewrites those two prefixes into tmp_path, exactly as the setup-script
execution tests do, and alters nothing else about the commands it is given.

ONE THING REAL GIT CANNOT STAGE is a container that has stopped answering,
because that failure is not a git failure - the Docker backend RETURNS a
non-zero result rather than raising. `_BreaksOn` therefore wraps the real
workspace and replaces exactly one command's result with the shape an
unreachable container produces, leaving every other command real. That keeps
the sequence under test genuine right up to the point of failure.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    UnpushedWorkQuarantinedError,
    WorkspaceInspectionFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    _SCRATCH_INDEX,
    quarantine_unpushed_work,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_shared.workspace_paths import WORKSPACE_REPOS_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from syn_domain.contexts.orchestration._shared.ExecutionValueObjects import PhaseResult

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_EXECUTION_ID = "exec-5497fb20005b"
_PHASE_ID = "implement"
_QUARANTINE_REF = f"refs/syn/lost/{_EXECUTION_ID}/{_PHASE_ID}"
_REPO = "syntropic137"
_BRANCH = "fix/1184-quarantine-unpushed-work"


def _git(*args: str, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """Run git with an identity and no user/system config to inherit."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


class _Workspace:
    """Runs the gate's commands for real, against repositories on disk.

    Deliberately provides NO git identity and NO global config: the container
    may have none either, so a gate that relied on inheriting one would fail
    here rather than only in production.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._home = root / "home"
        self._home.mkdir(exist_ok=True)

    def _rewrite(self, arg: str) -> str:
        return arg.replace(str(WORKSPACE_REPOS_DIR), str(self._root / "repos")).replace(
            _SCRATCH_INDEX, str(self._root / "quarantine.index")
        )

    async def execute(self, command: list[str]) -> ExecutionResult:
        proc = subprocess.run(
            [self._rewrite(arg) for arg in command],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(self._home),
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
            },
        )
        return ExecutionResult(
            exit_code=proc.returncode,
            success=proc.returncode == 0,
            duration_ms=0.0,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


class _Clone:
    """A clone of a bare origin, plus the reads the assertions need."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.origin = root / "origin.git"
        self.path = root / "repos" / _REPO
        self.workspace = _Workspace(root)

    def git(self, *args: str) -> str:
        return _git(*args, cwd=self.path, home=self.root / "home").stdout.strip()

    def origin_git(self, *args: str) -> str:
        return _git(*args, cwd=self.origin, home=self.root / "home").stdout.strip()

    def origin_refs(self) -> dict[str, str]:
        listing = _git(
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            cwd=self.origin,
            home=self.root / "home",
        ).stdout
        return dict(
            line.split(" ", 1)
            for line in listing.splitlines()
            if line  # type: ignore[misc]
        )

    def commit(self, name: str, content: str) -> str:
        (self.path / name).write_text(content)
        self.git("add", name)
        self.git("commit", "-m", f"add {name}")
        return self.git("rev-parse", "HEAD")

    def advance_origin_main(self, name: str, content: str) -> None:
        """Move origin/main on, the way another PR merging does, and fetch it."""
        seed = self.root / "seed"
        (seed / name).write_text(content)
        _git("add", name, cwd=seed, home=self.root / "home")
        _git("commit", "-m", f"add {name}", cwd=seed, home=self.root / "home")
        _git("push", str(self.origin), "main", cwd=seed, home=self.root / "home")
        self.git("fetch", "origin")

    def parents_of(self, sha: str) -> list[str]:
        return self.git("rev-list", "--parents", "-n", "1", sha).split()[1:]

    def reachable_in_origin(self, sha: str, ref: str) -> bool:
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, ref],
                cwd=self.origin,
                check=False,
            ).returncode
            == 0
        )

    async def run_gate(self) -> None:
        await quarantine_unpushed_work(
            self.workspace, execution_id=_EXECUTION_ID, phase_id=_PHASE_ID
        )


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A pushed-up-to-date clone on a feature branch - a phase's starting point."""
    repo = _Clone(tmp_path)
    (tmp_path / "home").mkdir(exist_ok=True)
    repo.origin.mkdir(parents=True)
    _git("init", "--bare", "--initial-branch=main", ".", cwd=repo.origin, home=tmp_path / "home")

    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "--initial-branch=main", ".", cwd=seed, home=tmp_path / "home")
    (seed / "README.md").write_text("seed\n")
    _git("add", "README.md", cwd=seed, home=tmp_path / "home")
    _git("commit", "-m", "seed", cwd=seed, home=tmp_path / "home")
    _git("push", str(repo.origin), "main", cwd=seed, home=tmp_path / "home")

    repo.path.parent.mkdir(parents=True)
    _git("clone", str(repo.origin), str(repo.path), cwd=tmp_path, home=tmp_path / "home")
    repo.git("checkout", "-b", _BRANCH)
    repo.git("push", "-u", "origin", _BRANCH)
    return repo


async def test_an_unpushed_merge_commit_fails_the_phase_and_survives(clone: _Clone) -> None:
    """(a) THE ORIGINAL INCIDENT SHAPE, reproduced rather than evoked.

    On PR #1072 the implement phase merged origin/main into its branch and the
    merge commit stayed local: the workspace died, the execution reported
    completed, and ``merge-base --is-ancestor origin/main HEAD`` still exited 1
    hours later. So this builds a genuine ``--no-ff`` merge - two parents, both
    already on the remote, the merge itself on nothing - and asserts the merge
    SHA is an ancestor of the quarantine ref, which is the same question that
    exited 1 during the incident.

    The two-parent assertion is not decoration. A single-parent commit named
    "merge" would pass every other line here while testing a shape the incident
    never had, which is what this test used to do.
    """
    branch_head_before = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    clone.advance_origin_main("upstream.py", "another PR landed on main\n")
    clone.git("merge", "--no-ff", "-m", "Merge origin/main", "origin/main")
    merge = clone.git("rev-parse", "HEAD")
    assert len(clone.parents_of(merge)) == 2, "this test must merge, not commit"

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await clone.run_gate()

    assert clone.origin_git("rev-parse", "--verify", f"{_QUARANTINE_REF}^{{commit}}")
    assert clone.reachable_in_origin(merge, _QUARANTINE_REF), (
        "the unpushed merge commit is not reachable from the quarantine ref"
    )
    # Only the merge is unpushed - both of its parents were already on a remote.
    message = str(raised.value)
    assert _QUARANTINE_REF in message
    assert _BRANCH in message
    assert "1 commit(s) on no remote" in message
    # And nothing anyone reviews moved.
    assert clone.origin_refs()[f"refs/heads/{_BRANCH}"] == branch_head_before


async def test_a_plain_commit_that_was_never_pushed_is_saved_too(clone: _Clone) -> None:
    """The simpler half of (a): one ordinary commit, never pushed."""
    lost = clone.commit("stranded.py", "committed, never pushed\n")

    with pytest.raises(UnpushedWorkQuarantinedError):
        await clone.run_gate()

    assert clone.reachable_in_origin(lost, _QUARANTINE_REF)


async def test_b_uncommitted_changes_fail_the_phase_and_survive(clone: _Clone) -> None:
    """(b) Edits to a tracked file that were never committed are saved too."""
    branch_head_before = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    (clone.path / "README.md").write_text("edited but never committed\n")

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await clone.run_gate()

    assert (
        clone.origin_git("show", f"{_QUARANTINE_REF}:README.md") == "edited but never committed"
    ), "the quarantine ref does not carry the uncommitted content"
    message = str(raised.value)
    assert _QUARANTINE_REF in message
    assert "README.md" in message
    assert clone.origin_refs()[f"refs/heads/{_BRANCH}"] == branch_head_before


async def test_c_a_phase_that_pushed_everything_succeeds(clone: _Clone) -> None:
    """(c) Work that reached the remote is not work that would be lost."""
    clone.commit("shipped.py", "pushed properly\n")
    clone.git("push", "origin", _BRANCH)

    await clone.run_gate()

    assert not [ref for ref in clone.origin_refs() if ref.startswith("refs/syn/lost/")]


async def test_d_a_phase_that_changed_nothing_succeeds(clone: _Clone) -> None:
    """(d) THE TRUE NEGATIVE: a phase that only reads or reports is not a failure.

    A bootstrap that answers a question and a verify that only inspects both
    end with a clean tree and nothing to push. They must complete. A gate that
    fires here would fail every read-only phase in the system.
    """
    await clone.run_gate()

    assert not [ref for ref in clone.origin_refs() if ref.startswith("refs/syn/lost/")]


async def test_e_quarantining_touches_no_branch_and_no_tag(clone: _Clone) -> None:
    """(e) The quarantine push writes one ref and moves nothing else."""
    before = clone.origin_refs()
    clone.commit("stranded.py", "work\n")

    with pytest.raises(UnpushedWorkQuarantinedError):
        await clone.run_gate()

    after = clone.origin_refs()
    assert {
        ref: sha for ref, sha in after.items() if not ref.startswith("refs/syn/lost/")
    } == before
    assert set(after) - set(before) == {_QUARANTINE_REF}


async def test_commits_on_a_branch_that_is_not_checked_out_are_saved_too(clone: _Clone) -> None:
    """A tip with no upstream still carries work, checked out or not.

    The third detection condition in #1184. It is asserted separately because
    quarantining it is what makes the quarantine commit's parent list plural -
    detecting this case and then pushing only HEAD would fail the phase while
    still losing exactly the work it just named.
    """
    stranded = clone.commit("stranded.py", "committed, then abandoned\n")
    clone.git("branch", "side-quest")
    clone.git("reset", "--hard", "origin/" + _BRANCH)

    with pytest.raises(UnpushedWorkQuarantinedError):
        await clone.run_gate()

    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", stranded, _QUARANTINE_REF],
            cwd=clone.origin,
            check=False,
        ).returncode
        == 0
    ), "work on a branch that was not checked out was named but not saved"


async def test_the_phase_that_holds_unpushed_work_is_never_reported_completed(
    clone: _Clone,
) -> None:
    """The consuming hop: COMPLETE_PHASE must not reach the aggregate.

    The defect was never in the detection - it was that a phase reported
    ``completed`` with its work gone. So this asserts against the aggregate the
    processor would have told, not against the guard's return value.
    """
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    clone.commit("never-pushed.py", "work the workspace was about to eat\n")
    processor = WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=MagicMock(),
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="prompt"),
        command_builder=MagicMock(return_value=["claude"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
    )
    processor._active_workspaces[_PHASE_ID] = clone.workspace  # type: ignore[assignment]
    aggregate = MagicMock(workflow_id="wf-1")
    completed_phase_ids: list[str] = []

    async def complete() -> None:
        await processor._handle_complete_phase(
            TodoItem(
                execution_id=_EXECUTION_ID,
                action=TodoAction.COMPLETE_PHASE,
                phase_id=_PHASE_ID,
                session_id="sess-1",
            ),
            ExecutablePhase(
                phase_id=_PHASE_ID,
                name="Implement",
                order=1,
                agent_config=AgentConfiguration(provider="claude"),
                prompt_template="do it",
            ),
            aggregate,
            [],
            completed_phase_ids,
        )

    with pytest.raises(UnpushedWorkQuarantinedError):
        await complete()

    aggregate.complete_phase.assert_not_called()
    assert completed_phase_ids == []


# --------------------------------------------------------------------------
# The workspace that stopped answering.
#
# An unreachable container is NOT an exception: AgenticIsolationAdapter.execute
# returns ExecutionResult(success=False, ...) with empty stdout, and the Docker
# provider behind it does the same for a container that has died. Empty stdout
# is also what a clean workspace returns, which is the whole defect.
# --------------------------------------------------------------------------

#: Every command whose output the gate reads as repository state. `push` is
#: absent on purpose - its failure is reported as data, not raised on - and it
#: has a test of its own.
_LOAD_BEARING = (
    "find",
    "status",
    "for-each-ref",
    "rev-parse",
    "rev-list",
    "rm",
    "add",
    "write-tree",
    "commit-tree",
)

_UNREACHABLE = ExecutionResult(
    exit_code=-1,
    success=False,
    duration_ms=0.0,
    stdout="",
    stderr="Container not available",
)


def _operation(command: list[str]) -> str:
    """What this argv is doing: the git subcommand, or the bare program."""
    if "git" in command:
        return command[command.index("git") + 3]  # git, -C, <repo>, <subcommand>
    return command[0]


class _BreaksOn:
    """The real workspace, except one command answers like a dead container."""

    def __init__(self, inner: _Workspace, failing: str) -> None:
        self._inner = inner
        self._failing = failing
        self.attempted: list[str] = []

    async def execute(self, command: list[str]) -> ExecutionResult:
        operation = _operation(command)
        self.attempted.append(operation)
        if operation == self._failing:
            return _UNREACHABLE
        return await self._inner.execute(command)


class _NoRepositories:
    """A reachable workspace holding no repositories at all.

    Exit 0 and empty stdout - the TRUE NEGATIVE. `/workspace/repos` is created
    by the image and again by the entrypoint, so a find that matches nothing
    there still exits 0. Any command other than that find is a bug: with no
    repositories there is nothing to inspect.
    """

    async def execute(self, command: list[str]) -> ExecutionResult:
        assert _operation(command) == "find", f"unexpected command {command}"
        return ExecutionResult(exit_code=0, success=True, duration_ms=0.0, stdout="", stderr="")


class _PhaseRun:
    """A phase at COMPLETE_PHASE, and the processor about to complete it.

    The consuming hop, not the guard: the defect #1184 names is a phase
    REPORTED completed, so every assertion here is about what the aggregate was
    told and what teardown ran, never about the guard's return value.
    """

    def __init__(self, workspace: object) -> None:
        from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
        from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
            ExecutionTodoProjection,
        )

        self.aggregate = MagicMock(workflow_id="wf-1")
        self.aggregate._uncommitted_events = []
        self.completed_phase_ids: list[str] = []
        self.phase_results: list[PhaseResult] = []
        self.session = AsyncMock()
        self.processor = WorkflowExecutionProcessor(
            execution_repository=AsyncMock(),
            session_repository=AsyncMock(),
            workspace_service=MagicMock(),
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="prompt"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        )
        self.processor._active_workspaces[_PHASE_ID] = workspace  # type: ignore[assignment]
        self.processor._session_managers[_PHASE_ID] = self.session  # type: ignore[assignment]

    @property
    def workspace_still_held(self) -> bool:
        return _PHASE_ID in self.processor._active_workspaces

    async def complete(self) -> None:
        await self.processor._handle_complete_phase(
            TodoItem(
                execution_id=_EXECUTION_ID,
                action=TodoAction.COMPLETE_PHASE,
                phase_id=_PHASE_ID,
                session_id="sess-1",
            ),
            ExecutablePhase(
                phase_id=_PHASE_ID,
                name="Implement",
                order=1,
                agent_config=AgentConfiguration(provider="claude"),
                prompt_template="do it",
            ),
            self.aggregate,
            self.phase_results,
            self.completed_phase_ids,
        )

    async def fail_the_way_the_engine_does(self, error: Exception) -> object:
        """Exactly what execute_workflow's own `except Exception` does next."""
        return await self.processor._fail_execution(
            error,
            self.aggregate,
            _EXECUTION_ID,
            "wf-1",
            [],
            self.phase_results,
            [],
            self.completed_phase_ids,
            datetime.now(UTC),
            failed_phase_id=_PHASE_ID,
        )


async def test_a_find_that_fails_never_lets_the_phase_complete(clone: _Clone) -> None:
    """(a) An unreachable workspace is not a clean one.

    THE DEFECT THIS PINS. `find` returning non-zero with empty stdout was read
    as "no repositories here", the gate returned silently, and the phase was
    reported completed - #1184 happening inside the gate written to prevent it.
    The repository below is holding an unpushed commit the whole time.
    """
    clone.commit("never-pushed.py", "work the workspace was about to eat\n")
    run = _PhaseRun(_BreaksOn(clone.workspace, "find"))

    with pytest.raises(WorkspaceInspectionFailedError):
        await run.complete()

    run.aggregate.complete_phase.assert_not_called()
    assert run.completed_phase_ids == []


async def test_b_the_execution_records_the_inspection_failure_not_completion(
    clone: _Clone,
) -> None:
    """(b) What the execution is left saying: failed, by name, not completed.

    The type name is what a human reading the failed execution sees, so it has
    to be the specific one - a generic Exception would be indistinguishable
    from any other phase failure and would send the reader looking in the
    wrong place.
    """
    clone.commit("never-pushed.py", "work\n")
    run = _PhaseRun(_BreaksOn(clone.workspace, "find"))

    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()
    result = await run.fail_the_way_the_engine_does(raised.value)

    run.aggregate.complete_phase.assert_not_called()
    run.aggregate.fail_execution.assert_called_once()
    recorded = run.aggregate.fail_execution.call_args.args[0]
    assert recorded.error_type == "WorkspaceInspectionFailedError"
    assert recorded.failed_phase_id == _PHASE_ID
    assert "Container not available" in recorded.error
    assert getattr(result, "status", None) == "failed"


@pytest.mark.parametrize("failing", _LOAD_BEARING)
async def test_c_any_load_bearing_command_failing_stops_the_phase(
    clone: _Clone, failing: str
) -> None:
    """(c) The CLASS of defect, not the one call site.

    Every command whose stdout the gate turns into repository state gets the
    same treatment, so a fifth unchecked command cannot quietly reopen the
    hole. The repository holds an unpushed commit, which is what carries
    execution past inspection and into the quarantine-building commands.
    """
    clone.commit("never-pushed.py", "work\n")
    workspace = _BreaksOn(clone.workspace, failing)
    run = _PhaseRun(workspace)

    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    assert failing in workspace.attempted, "the command under test never ran"
    run.aggregate.complete_phase.assert_not_called()
    # (3) Nothing was written, so nothing may be described as quarantined.
    message = str(raised.value)
    assert "quarantined at" not in message
    assert "NOTHING WAS QUARANTINED" in message
    assert not [ref for ref in clone.origin_refs() if ref.startswith("refs/syn/lost/")]


async def test_d_a_failed_inspection_leaves_teardown_to_the_failure_path(
    clone: _Clone,
) -> None:
    """(d) The completion path tears nothing down; the failure path does.

    The recoverability contract. `_handle_complete_phase` must not pop the
    workspace or report the session a success on its way out - a command can
    fail for reasons that leave the container alive, and destroying it from the
    success path would remove the only thing an operator could still look at.
    Teardown belongs to the failure path, which also closes the session as a
    FAILURE rather than a success.
    """
    clone.commit("never-pushed.py", "work\n")
    run = _PhaseRun(_BreaksOn(clone.workspace, "status"))

    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    assert run.workspace_still_held, "the completion path tore the workspace down"
    run.session.complete_success.assert_not_called()

    await run.fail_the_way_the_engine_does(raised.value)

    run.session.complete_failure.assert_called_once()
    assert not run.workspace_still_held, "the failure path left the workspace open"


async def test_e_a_workspace_with_no_repositories_still_completes(clone: _Clone) -> None:
    """(e) THE TRUE NEGATIVE THAT MUST NOT REGRESS.

    Exit 0 with empty stdout is a real answer: an execution configured with no
    repositories, which several self-host workflows have. A guard that failed
    these would break every read-only phase in the system - strictly worse than
    the bug it fixes. This asserts the aggregate WAS told, not merely that
    nothing raised, because "did not raise" is also true of a phase that never
    got that far.
    """
    run = _PhaseRun(_NoRepositories())

    await run.complete()

    run.aggregate.complete_phase.assert_called_once()
    assert run.completed_phase_ids == [_PHASE_ID]


async def test_e_at_the_gate_an_empty_but_reachable_workspace_is_silence() -> None:
    """(e) The same true negative one hop down, at the gate itself."""
    await quarantine_unpushed_work(
        _NoRepositories(), execution_id=_EXECUTION_ID, phase_id=_PHASE_ID
    )


async def test_f_a_failed_quarantine_push_fails_the_phase_and_says_so(clone: _Clone) -> None:
    """(f) The push is allowed to fail, and then the report must not soften it.

    A push can fail while the workspace is perfectly reachable - no credential,
    no network, a rejecting remote - so unlike every other command its non-zero
    result is data rather than an error. What must not happen is the phase
    completing anyway, or the message implying the work is recoverable when the
    ref it would be recovered from does not exist.
    """
    clone.commit("never-pushed.py", "work\n")
    run = _PhaseRun(_BreaksOn(clone.workspace, "push"))

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await run.complete()

    run.aggregate.complete_phase.assert_not_called()
    message = str(raised.value)
    assert "NOT RECOVERABLE" in message
    assert "quarantined at" not in message
    assert "git fetch origin" not in message
    assert not [ref for ref in clone.origin_refs() if ref.startswith("refs/syn/lost/")]


async def test_a_repository_with_no_commits_yet_is_not_an_unreachable_one(
    clone: _Clone,
) -> None:
    """An unborn HEAD is an answer, and answering it must not need a carve-out.

    `git rev-parse --quiet --verify HEAD` exits 1 in a repository with no
    commits - the same non-zero-with-empty-stdout shape as an unreachable
    workspace, and therefore unusable here. `--revs-only` exits 0, so the case
    stops existing instead of needing an exception carved into the checking.
    The file left behind is what makes the phase fail: the repository is empty,
    but the work in it is real.
    """
    empty = clone.root / "repos" / "brand-new"
    empty.mkdir()
    _git("init", "--initial-branch=main", ".", cwd=empty, home=clone.root / "home")
    (empty / "written.py").write_text("made in a repository with no history\n")

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await clone.run_gate()

    message = str(raised.value)
    assert "brand-new (branch (no commits))" in message
    assert "written.py" in message
