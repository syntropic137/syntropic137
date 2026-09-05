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
"""

from __future__ import annotations

import os
import subprocess
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


async def test_a_commit_that_was_never_pushed_fails_the_phase_and_survives(clone: _Clone) -> None:
    """(a) A phase that commits without pushing fails, and the commit is saved."""
    branch_head_before = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
    lost = clone.commit("merged.py", "the merge that never existed\n")

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await clone.run_gate()

    # The commit is genuinely in the origin, reachable from the quarantine ref.
    assert clone.origin_git("rev-parse", "--verify", f"{_QUARANTINE_REF}^{{commit}}")
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", lost, _QUARANTINE_REF],
            cwd=clone.origin,
            check=False,
        ).returncode
        == 0
    ), "the unpushed commit is not reachable from the quarantine ref"
    # The error names the ref, the branch and the count, so the next run can act.
    message = str(raised.value)
    assert _QUARANTINE_REF in message
    assert _BRANCH in message
    assert "1 commit(s) on no remote" in message
    # (e) and nothing anyone reviews moved.
    assert clone.origin_refs()[f"refs/heads/{_BRANCH}"] == branch_head_before


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
