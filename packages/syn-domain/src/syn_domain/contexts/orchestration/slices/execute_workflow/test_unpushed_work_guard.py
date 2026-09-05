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
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    QuarantinedWork,
    UnpushedWorkQuarantinedError,
    WorkspaceInspectionFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    _SCRATCH_INDEX,
    GitWorkspace,
    quarantine_unpushed_work,
    refuse_to_complete_unsaved_phase,
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
    """A named clone of its own bare origin, plus the reads the assertions need.

    NAMED because the gate walks a workspace's repositories one at a time, so
    a workspace holding two of them is a different program from one holding
    one - and each needs its own origin for "is this work durable" to be a
    question about that repository rather than a shared one.
    """

    def __init__(self, root: Path, name: str) -> None:
        self.root = root
        self.name = name
        self.origin = root / f"{name}.origin.git"
        self.seed = root / f"{name}.seed"
        self.path = root / "repos" / name
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

    def push_from_elsewhere(self, name: str, content: str) -> str:
        """Move `<branch>` ON THE ORIGIN from a SECOND clone, and tell this one nothing.

        THE PRODUCTION INPUT EVERY OTHER HELPER OMITS, and the only one that
        can tell a reading of the remote apart from a reading of the cache. A
        push made from THIS clone updates its `refs/remotes` as a side effect,
        so a fixture built that way leaves the cache correct and any
        implementation passes. Pushing from somewhere else, and never
        fetching, leaves this clone's cache holding a commit that is no longer
        where the branch is - which is what a phase that pushed nothing and
        failed while a teammate pushed actually looks like.

        Returns the commit the ORIGIN now holds, read from the second clone.
        """
        elsewhere = self.root / f"{self.name}.elsewhere"
        if not elsewhere.exists():
            _git("clone", str(self.origin), str(elsewhere), cwd=self.root, home=self.root / "home")
            _git("checkout", _BRANCH, cwd=elsewhere, home=self.root / "home")
        (elsewhere / name).write_text(content)
        _git("add", name, cwd=elsewhere, home=self.root / "home")
        _git("commit", "-m", f"add {name}", cwd=elsewhere, home=self.root / "home")
        _git("push", "origin", _BRANCH, cwd=elsewhere, home=self.root / "home")
        return _git("rev-parse", "HEAD", cwd=elsewhere, home=self.root / "home").stdout.strip()

    def cached_remote_tip(self, branch: str = _BRANCH) -> str:
        """What THIS clone last heard `origin/<branch>` was, from `refs/remotes`."""
        return self.git("rev-parse", f"refs/remotes/origin/{branch}")

    def hang_the_remote(self, seconds: int) -> None:
        """Point origin at a transport that answers nothing for ``seconds``.

        `ext::` runs the given program as the transport helper, so `sleep`
        gives a remote that is REACHABLE and simply never speaks - the failure
        an unreachable-host URL cannot stage, because that one ends by itself.
        Only this one can show that something else ends it. Enabled per
        repository because git refuses `ext::` by default, which is a good
        default and not one the gate has any reason to change.
        """
        self.git("config", "protocol.ext.allow", "always")
        self.git("remote", "set-url", "origin", f"ext::sleep {seconds}")

    def break_the_remote(self) -> None:
        """Point origin somewhere that does not exist, so asking it fails.

        A path rather than an unreachable host: it fails immediately and
        identically on every machine, where a bad URL would spend the
        suite's time discovering that. "The remote is gone" is one of the
        real failure modes, and the code cannot tell it from the others.
        """
        self.git("remote", "set-url", "origin", str(self.root / "no-such-origin.git"))

    def advance_origin_main(self, name: str, content: str) -> None:
        """Move origin/main on, the way another PR merging does, and fetch it."""
        seed = self.seed
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


def _clone_repository(root: Path, name: str = _REPO) -> _Clone:
    """A bare origin, a seeded main, and a clone of it on a feature branch.

    A function rather than only a fixture because the interesting workspace
    has TWO repositories in it, and pytest cannot hand the same fixture out
    twice under different names.
    """
    repo = _Clone(root, name)
    (root / "home").mkdir(exist_ok=True)
    repo.origin.mkdir(parents=True)
    _git("init", "--bare", "--initial-branch=main", ".", cwd=repo.origin, home=root / "home")

    repo.seed.mkdir()
    _git("init", "--initial-branch=main", ".", cwd=repo.seed, home=root / "home")
    (repo.seed / "README.md").write_text("seed\n")
    _git("add", "README.md", cwd=repo.seed, home=root / "home")
    _git("commit", "-m", "seed", cwd=repo.seed, home=root / "home")
    _git("push", str(repo.origin), "main", cwd=repo.seed, home=root / "home")

    repo.path.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", str(repo.origin), str(repo.path), cwd=root, home=root / "home")
    repo.git("checkout", "-b", _BRANCH)
    repo.git("push", "-u", "origin", _BRANCH)
    return repo


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A pushed-up-to-date clone on a feature branch - a phase's starting point."""
    return _clone_repository(tmp_path)


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
    processor._runtime._workspaces[_PHASE_ID] = clone.workspace  # type: ignore[assignment]
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
            aggregate,
            [],
            completed_phase_ids,
        )

    with pytest.raises(UnpushedWorkQuarantinedError):
        await complete()

    aggregate.complete_phase.assert_not_called()
    assert completed_phase_ids == []


# --------------------------------------------------------------------------
# The wiring hop.
#
# `_handle_complete_phase` no longer looks a workspace up, and no longer
# decides what a missing one means: `refuse_to_complete_unsaved_phase` owns
# both. Every other test in this file calls `quarantine_unpushed_work`
# directly with the module constants, so all of them would still pass if that
# hop forwarded the wrong workspace, or ids it had invented rather than read.
# These four are about the hop itself.
# --------------------------------------------------------------------------


class _NeverRun:
    """A workspace that fails the test if the gate reaches it at all."""

    async def execute(self, command: list[str]) -> ExecutionResult:
        raise AssertionError(f"ran {command} for a phase it was not asked about")


def _completing(phase_id: str | None, execution_id: str = _EXECUTION_ID) -> TodoItem:
    return TodoItem(
        execution_id=execution_id,
        action=TodoAction.COMPLETE_PHASE,
        phase_id=phase_id,
        session_id="sess-1",
    )


async def test_the_ref_is_named_from_the_todo_the_hop_was_handed(tmp_path: Path) -> None:
    """The ids survive the hop as far as the ref an operator has to fetch.

    BOTH ids differ from the module constants deliberately. The value that
    matters is not one the gate could have defaulted to: a hop that read the
    ids from anywhere other than this `TodoItem` would still push a
    plausible-looking ref, and every other test here would still be green.
    """
    clone = _clone_repository(tmp_path)
    clone.commit("never-pushed.py", "work the workspace was about to eat\n")

    with pytest.raises(UnpushedWorkQuarantinedError):
        await refuse_to_complete_unsaved_phase(
            {"verify": clone.workspace},
            _completing("verify", execution_id="exec-a-different-run"),
        )

    refs = clone.origin_refs()
    assert "refs/syn/lost/exec-a-different-run/verify" in refs
    assert _QUARANTINE_REF not in refs, "the ref was named from something other than the todo"


async def test_the_hop_inspects_the_phase_its_todo_names_and_no_other(tmp_path: Path) -> None:
    """The map holds every live phase; only the one completing is at stake.

    The phase that is NOT completing holds unpushed work here. Failing this
    phase for it would strand a phase that is still running, and each phase
    gets its own COMPLETE_PHASE to be judged at.
    """
    roots = {name: tmp_path / name for name in ("completing", "running")}
    for root in roots.values():
        root.mkdir()
    completing = _clone_repository(roots["completing"])
    running = _clone_repository(roots["running"])
    running.commit("never-pushed.py", "another phase's work, still in progress\n")

    await refuse_to_complete_unsaved_phase(
        {"implement": running.workspace, "verify": completing.workspace},
        _completing("verify"),
    )

    saved = [ref for ref in running.origin_refs() if ref.startswith("refs/syn/lost/")]
    assert saved == [], "the hop quarantined a phase that was not completing"


async def test_a_phase_whose_workspace_is_already_gone_is_holding_nothing() -> None:
    """Absence is a verdict, not a check that was skipped.

    Nothing that no longer exists can lose work by being destroyed again, so
    the phase completes - and the gate must not go looking in some other
    phase's workspace for something to say about this one.
    """
    await refuse_to_complete_unsaved_phase({"implement": _NeverRun()}, _completing("verify"))


async def test_a_todo_with_no_phase_names_no_workspace_and_so_holds_nothing() -> None:
    """`phase_id` is optional on `TodoItem`, and there is no phase to key on.

    Unreachable from the processor, which asserts it first. Stated here so the
    hop has one answer for "no workspace to inspect" however it arises, rather
    than a `None` key that quietly matches nothing.
    """
    await refuse_to_complete_unsaved_phase({"implement": _NeverRun()}, _completing(None))


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
    """The real workspace, except one command answers like a dead container.

    ``in_repo`` narrows that to a single repository, which a multi-repository
    workspace needs: without it "status fails" means status fails everywhere,
    and then no repository ever gets far enough to be quarantined before the
    failure - which is precisely the transition worth testing.

    ``inner`` is the gate's own port rather than `_Workspace`, so these NEST.
    The mixed cell - one repository quarantined, one whose push failed, and a
    third that stopped answering - needs two different commands to fail in two
    different repositories, and wrapping twice says that without this class
    growing a second way to describe a failure.
    """

    def __init__(self, inner: GitWorkspace, failing: str, *, in_repo: str | None = None) -> None:
        self._inner = inner
        self._failing = failing
        self._in_repo = in_repo
        self.attempted: list[str] = []

    async def execute(self, command: list[str]) -> ExecutionResult:
        operation = _operation(command)
        self.attempted.append(operation)
        if operation == self._failing and (self._in_repo is None or self._in_repo in command):
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
        self.processor._runtime._workspaces[_PHASE_ID] = workspace  # type: ignore[assignment]
        self.processor._runtime.begin(
            _PHASE_ID,
            session_manager=self.session,  # type: ignore[arg-type]
            started_at=datetime.now(UTC),
        )

    @property
    def workspace_still_held(self) -> bool:
        return _PHASE_ID in self.processor._runtime.live_workspaces

    async def complete(self) -> None:
        await self.processor._handle_complete_phase(
            TodoItem(
                execution_id=_EXECUTION_ID,
                action=TodoAction.COMPLETE_PHASE,
                phase_id=_PHASE_ID,
                session_id="sess-1",
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


# --------------------------------------------------------------------------
# More than one repository, which is where "nothing was saved" can be a lie.
#
# `quarantine_unpushed_work` walks a workspace's repositories SEQUENTIALLY, so
# the first one's work can already be pushed and durable in its own origin at
# the moment a command for the second one fails. Every fixture above holds
# exactly ONE repository, and at that size the program that reports those
# survivors and the program that discards them are indistinguishable.
# --------------------------------------------------------------------------


async def test_work_quarantined_before_a_later_repository_failed_is_reported_as_saved(
    clone: _Clone, tmp_path: Path
) -> None:
    """The gate must not tell an operator nothing was saved when something was.

    THE DEFECT THIS PINS. `WorkspaceInspectionFailedError` used to append
    NOTHING WAS QUARANTINED unconditionally. On a workspace where an earlier
    repository's quarantine ref had ALREADY been pushed, that sentence was
    false in the one direction that costs the work: an operator told nothing
    was saved does not go looking for a ref that exists. That is #1184 itself -
    a confident claim nobody checked - pointing the other way, which is why the
    wording is a correctness surface here and not prose.

    The surviving ref is read back out of `alpha`'s OWN origin rather than off
    the error object, because the claim under test is that the work is durable
    and only the origin can answer that.
    """
    saved, doomed = _clone_repository(tmp_path, "alpha"), clone
    assert saved.path.name < doomed.path.name, (
        "the gate walks repositories in sorted order, and this test needs "
        "'alpha' fully quarantined BEFORE the other repository stops answering"
    )
    lost = saved.commit("stranded.py", "work only the quarantine ref will hold\n")

    workspace = _BreaksOn(clone.workspace, "status", in_repo=str(doomed.path))
    run = _PhaseRun(workspace)
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    # (1) alpha's work IS durable - the ref exists in alpha's origin and the
    #     commit that would have been lost is reachable from it.
    assert saved.origin_git("rev-parse", "--verify", f"{_QUARANTINE_REF}^{{commit}}")
    assert saved.reachable_in_origin(lost, _QUARANTINE_REF), (
        "alpha's unpushed commit is not reachable from its quarantine ref"
    )
    # (2) The repository that stopped answering got no ref: the gate failed
    #     before it had anything to write, which is what makes (3) a partial
    #     rather than a total.
    assert not [ref for ref in doomed.origin_refs() if ref.startswith("refs/syn/lost/")]

    # (3) THE ASSERTION THIS TEST EXISTS FOR: the error text is TRUE.
    message = str(raised.value)
    assert "NOTHING WAS QUARANTINED" not in message, (
        f"the gate claimed nothing was saved while alpha's quarantine ref "
        f"exists in its origin:\n{message}"
    )
    assert "alpha" in message, "the operator is not told WHICH repository survived"
    assert f"quarantined at {_QUARANTINE_REF}" in message
    assert f"recover with: git fetch origin {_QUARANTINE_REF}" in message

    # And the phase still fails: naming the survivors is not softening the verdict.
    run.aggregate.complete_phase.assert_not_called()
    assert run.completed_phase_ids == []


async def test_a_failure_in_the_first_repository_still_says_nothing_was_quarantined(
    clone: _Clone, tmp_path: Path
) -> None:
    """The other half: when nothing WAS saved, the message must still say so.

    Fixing the multi-repository lie by making the wording vague would trade one
    lost half of the truth for the other. So this is the same two-repository
    workspace with the failure moved to the FIRST repository - genuinely
    nothing durable - and the categorical claim has to come back.
    """
    first, second = _clone_repository(tmp_path, "alpha"), clone
    second.commit("never-pushed.py", "work that never got its turn\n")

    run = _PhaseRun(_BreaksOn(clone.workspace, "status", in_repo=str(first.path)))
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    message = str(raised.value)
    assert "NOTHING WAS QUARANTINED" in message
    assert "quarantined at" not in message
    assert not [ref for ref in first.origin_refs() if ref.startswith("refs/syn/lost/")]
    assert not [ref for ref in second.origin_refs() if ref.startswith("refs/syn/lost/")]
    run.aggregate.complete_phase.assert_not_called()


# --------------------------------------------------------------------------
# The four states a partial walk can end in, and the message each one gets.
#
# THE CLASS OF DEFECT THESE PIN, which three reviews found three separate
# instances of. Every one was a categorical claim about durable state that was
# never checked against durable state: an unreachable workspace called clean,
# "NOTHING WAS QUARANTINED" while a ref existed, and "go and get them" while
# none did. The third came from a renderer that branched on whether its record
# tuple was EMPTY - so a tuple of nothing but FAILED pushes took the branch
# that says work is recoverable, four lines above its own NOT RECOVERABLE.
#
# Emptiness has three answers ("nothing reached", "all lost", "some lost")
# collapsed into one, so the whole space is enumerated here instead: zero
# entries, all pushes failed, some pushed, all pushed.
#
# EVERY ONE OF THESE ASSERTS AGAINST THE ORIGINS. The message is the thing
# under test and therefore cannot also be the oracle - each of the three
# failures above was invisible to a test that only read the exception payload.
# `_origins_holding_the_ref` queries refs/syn/lost in each bare origin, and
# the headline's own count is checked against what it returns.
# --------------------------------------------------------------------------


def _origins_holding_the_ref(*clones: _Clone) -> tuple[str, ...]:
    """Names of the repositories whose OWN origin really holds the quarantine ref."""
    return tuple(clone.name for clone in clones if _QUARANTINE_REF in clone.origin_refs())


async def test_cell_1_a_walk_that_saved_nothing_says_nothing_was_quarantined(
    tmp_path: Path,
) -> None:
    """Zero records: the walk got somewhere, and still has nothing to offer.

    Not the same as "the first repository failed" - `alpha` is inspected in
    full here and simply has nothing to save, so the failure in `beta` arrives
    with progress made and an empty tuple. A gate that reasoned "we got past a
    repository, so something must have survived" would be wrong exactly here,
    and `beta` is holding real work while it happens.
    """
    alpha, beta = _clone_repository(tmp_path, "alpha"), _clone_repository(tmp_path, "beta")
    beta.commit("never-pushed.py", "work that never got its turn\n")

    run = _PhaseRun(_BreaksOn(alpha.workspace, "status", in_repo=str(beta.path)))
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    assert _origins_holding_the_ref(alpha, beta) == ()
    message = str(raised.value)
    assert "NOTHING WAS QUARANTINED: this phase's work is unverified" in message
    assert "quarantined at" not in message
    assert "NOT RECOVERABLE" not in message
    run.aggregate.complete_phase.assert_not_called()
    assert run.completed_phase_ids == []


async def test_cell_2_records_whose_every_push_failed_are_not_work_that_survived(
    tmp_path: Path,
) -> None:
    """THE PASS-3 DEFECT, reproduced: a non-empty tuple with nothing durable.

    `alpha` holds work, its quarantine push fails, and the record for it is
    carried into the error when `beta` stops answering. The tuple is non-empty
    and NOT ONE BYTE of it reached a remote - the renderer used to read the
    tuple's length as evidence of survival and print "SOME WORK WAS ALREADY
    QUARANTINED ... go and get them" above its own "NOT RECOVERABLE".

    The origins are queried because they are the only thing that can settle
    it: no `refs/syn/lost` ref exists in either of them.
    """
    alpha, beta = _clone_repository(tmp_path, "alpha"), _clone_repository(tmp_path, "beta")
    alpha.commit("stranded.py", "work whose only hope was the quarantine push\n")

    workspace = _BreaksOn(
        _BreaksOn(alpha.workspace, "push", in_repo=str(alpha.path)),
        "status",
        in_repo=str(beta.path),
    )
    run = _PhaseRun(workspace)
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    assert "push" in workspace.attempted, "alpha's quarantine push never ran"
    assert _origins_holding_the_ref(alpha, beta) == (), (
        "this test needs a state where NOTHING is durable"
    )

    message = str(raised.value)
    assert "NOTHING WAS QUARANTINED: work was found in 1 repository" in message, (
        f"a tuple of failed pushes was reported as work that survived:\n{message}"
    )
    assert "alpha" in message, "the operator is not told where the lost work was"
    assert "NOT RECOVERABLE" in message
    assert "quarantined at" not in message
    assert "recover with: git fetch origin" not in message
    assert "go and get them" not in message
    run.aggregate.complete_phase.assert_not_called()
    assert run.completed_phase_ids == []


async def test_cell_3_a_mixed_walk_names_the_refs_that_exist_and_only_those(
    tmp_path: Path,
) -> None:
    """Some pushed, some not: the count must match the refs that exist.

    `alpha` is quarantined, `beta`'s push fails, `gamma` stops answering. An
    operator reading this has to be able to tell which repository they can
    actually recover, so the headline states how many refs exist and the
    per-repository lines say which. Both numbers are checked against the three
    origins rather than against the error.
    """
    alpha = _clone_repository(tmp_path, "alpha")
    beta = _clone_repository(tmp_path, "beta")
    gamma = _clone_repository(tmp_path, "gamma")
    saved_commit = alpha.commit("saved.py", "work the quarantine ref will hold\n")
    beta.commit("stranded.py", "work whose push will fail\n")

    run = _PhaseRun(
        _BreaksOn(
            _BreaksOn(alpha.workspace, "push", in_repo=str(beta.path)),
            "status",
            in_repo=str(gamma.path),
        )
    )
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    holding = _origins_holding_the_ref(alpha, beta, gamma)
    assert holding == ("alpha",), "this test needs exactly one durable ref"
    assert alpha.reachable_in_origin(saved_commit, _QUARANTINE_REF)

    message = str(raised.value)
    assert "PART OF THIS PHASE'S WORK WAS QUARANTINED" in message, (
        f"a mixed walk was reported as though all of it survived:\n{message}"
    )
    assert f"a ref exists for {len(holding)} repository and not for 1 repository" in message
    assert "NOTHING WAS QUARANTINED" not in message
    assert f"    quarantined at {_QUARANTINE_REF}" in message
    assert f"recover with: git fetch origin {_QUARANTINE_REF}" in message
    assert "NOT RECOVERABLE" in message
    assert "alpha" in message
    assert "beta" in message
    run.aggregate.complete_phase.assert_not_called()
    assert run.completed_phase_ids == []


async def test_cell_4_a_walk_whose_pushes_all_landed_says_go_and_get_them(
    tmp_path: Path,
) -> None:
    """All pushed: the one state in which "go and get them" is true.

    Two repositories quarantined before a third stops answering, and the
    headline's count is read back out of the origins that actually hold a ref.
    This is the state the old renderer printed for all three of the others.
    """
    alpha = _clone_repository(tmp_path, "alpha")
    beta = _clone_repository(tmp_path, "beta")
    gamma = _clone_repository(tmp_path, "gamma")
    alpha_commit = alpha.commit("one.py", "work\n")
    beta_commit = beta.commit("two.py", "more work\n")

    run = _PhaseRun(_BreaksOn(alpha.workspace, "status", in_repo=str(gamma.path)))
    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await run.complete()

    holding = _origins_holding_the_ref(alpha, beta, gamma)
    assert holding == ("alpha", "beta")
    assert alpha.reachable_in_origin(alpha_commit, _QUARANTINE_REF)
    assert beta.reachable_in_origin(beta_commit, _QUARANTINE_REF)

    message = str(raised.value)
    assert f"the gate finished {len(holding)} repositories before it stopped" in message
    assert "go and get them" in message
    assert "NOTHING WAS QUARANTINED" not in message
    assert "NOT RECOVERABLE" not in message
    run.aggregate.complete_phase.assert_not_called()
    assert run.completed_phase_ids == []


# --------------------------------------------------------------------------
# The same question asked of the OTHER error, where the walk finished.
#
# `UnpushedWorkQuarantinedError` lists the same records and shares the same
# per-repository rendering, and a push can fail there too. Its report ends by
# counting the refs that exist, from the same split, so a reader learns whether
# all, some or none of it can be fetched without adding the lines up
# themselves - and so neither error can drift away from the other.
# --------------------------------------------------------------------------


async def test_a_completed_walk_whose_pushes_all_failed_says_none_of_it_survived(
    tmp_path: Path,
) -> None:
    """Every push failed, so the summary must not leave that to be inferred."""
    alpha, beta = _clone_repository(tmp_path, "alpha"), _clone_repository(tmp_path, "beta")
    alpha.commit("one.py", "work\n")
    beta.commit("two.py", "more work\n")

    run = _PhaseRun(_BreaksOn(alpha.workspace, "push"))
    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await run.complete()

    assert _origins_holding_the_ref(alpha, beta) == ()
    message = str(raised.value)
    assert "NONE OF IT IS RECOVERABLE" in message
    assert "quarantined at" not in message
    assert "recover with: git fetch origin" not in message
    run.aggregate.complete_phase.assert_not_called()


async def test_a_completed_walk_with_one_failed_push_says_which_half_survived(
    tmp_path: Path,
) -> None:
    """Mixed, with the walk finishing: the count comes from the origins."""
    alpha, beta = _clone_repository(tmp_path, "alpha"), _clone_repository(tmp_path, "beta")
    alpha.commit("one.py", "work whose push will fail\n")
    saved_commit = beta.commit("two.py", "work that reaches its ref\n")

    run = _PhaseRun(_BreaksOn(alpha.workspace, "push", in_repo=str(alpha.path)))
    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await run.complete()

    holding = _origins_holding_the_ref(alpha, beta)
    assert holding == ("beta",)
    assert beta.reachable_in_origin(saved_commit, _QUARANTINE_REF)

    message = str(raised.value)
    assert f"PARTLY RECOVERABLE: a ref exists for {len(holding)} repository" in message
    assert "and not for 1 repository" in message
    assert "NOT RECOVERABLE" in message
    assert f"    quarantined at {_QUARANTINE_REF}" in message


async def test_a_completed_walk_whose_pushes_all_landed_says_all_of_it_survived(
    tmp_path: Path,
) -> None:
    """The fourth cell of the same enumeration, on the completed-walk error."""
    alpha, beta = _clone_repository(tmp_path, "alpha"), _clone_repository(tmp_path, "beta")
    alpha.commit("one.py", "work\n")
    beta.commit("two.py", "more work\n")

    run = _PhaseRun(alpha.workspace)
    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await run.complete()

    holding = _origins_holding_the_ref(alpha, beta)
    assert holding == ("alpha", "beta")
    message = str(raised.value)
    assert f"All of it is recoverable: a ref exists for {len(holding)} repositories" in message
    assert "NOT RECOVERABLE" not in message


def test_a_record_that_names_neither_a_ref_nor_a_reason_is_rejected() -> None:
    """A fifth entry shape must fail loudly rather than be given a message.

    The four cells above are exhaustive only because every record answers
    exactly one of "where is it" and "why is it nowhere". A record answering
    both or neither would make `is_recoverable` an interpretation rather than a
    fact, and the headline derived from it a guess - which is the whole family
    of defect this file exists to close. So the shape is refused where it is
    built, and no renderer downstream ever has to decide.
    """
    for pushed_ref, push_error in ((None, None), ("refs/syn/lost/x", "it also failed")):
        with pytest.raises(ValueError, match="exactly one of them"):
            QuarantinedWork(
                repo="alpha",
                branch="main",
                commit_count=1,
                files=(),
                pushed_ref=pushed_ref,
                push_error=push_error,
            )
