"""A review phase's checkout must not leave a submodule for the guard to find.

exec-5a22616362bd: the `verify` phase of the implement workflow ran for 21
minutes on codex, produced its review, and then failed at teardown with

    uncommitted:  M lib/syntropic137-claude-plugin

The agent had run no submodule command. Its prompt told it to
``git checkout <sha>``, and a plain checkout moves the superproject but not the
submodules: the commit under review pinned a different gitlink from the default
branch the workspace was cloned on, so the submodule stayed where the clone put
it and ``git status --porcelain`` reported it modified. The unpushed-work guard
reads every porcelain line as work - correctly, because it cannot tell a moved
gitlink from an authored one - and refused to report the phase complete. The
review was never stored.

THE FIX IS IN THE PROMPTS, NOT THE GUARD. Every review phase that checks out a
commit it did not write now does so with ``--recurse-submodules``, which removes
the cause of the dirt. The guard is untouched and still fails a phase that leaves
real work behind.

THE FIX COVERS THE CLASS, NOT THE ONE SIGHTING. Only `sdlc/implement` was
observed failing, but `sdlc/pr-review`, `sdlc/pr-review-slp` and the three
`custom/bake-*` workflows all carried the same plain checkout, so each was one
submodule bump away from the same refusal. `_REVIEW_PHASES` below is the whole
class; a new review phase added without the flag fails here rather than in
production after the review is paid for.

WHY THESE TESTS RUN THE GUARD AND NOT A GREP. A test that the prompt contains
``--recurse-submodules`` would pass for a flag in the wrong block, on the wrong
line, or on a command that never runs. What failed in production is the guard's
verdict on the tree the checkout left, so that is what is asserted: each
prompt's checkout block, as it reaches execution, is run in a workspace
cloned the way a phase arrives, and the resulting repository is handed to
`quarantine_unpushed_work` exactly as teardown would. Drop the flag from any one
prompt and its case raises `UnpushedWorkQuarantinedError` here.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.test_1290_a_moving_base_does_not_abort_a_review import (
    _prompt_reaching_execution,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _Workspace,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    quarantine_unpushed_work,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: Every review phase that checks out a commit it did not write. Each declares
#: `delivers_repo_changes: false`, so none may leave the tree dirty. The list is
#: the whole class, not the two phases that happened to fail in production: the
#: same plain checkout is in all of them, so the same guard refusal is one
#: submodule bump away in each.
_REVIEW_PHASES = [
    ("sdlc/implement", "verify"),
    ("sdlc/implement", "reverify"),
    ("sdlc/pr-review", "verify"),
    ("sdlc/pr-review-slp", "verify"),
    ("custom/bake-opus", "verify"),
    ("custom/bake-haiku", "verify"),
    ("custom/bake-sonnet", "verify"),
]

_FENCED_BLOCK = re.compile(r"^```[a-z]*\n(.*?)^```", re.MULTILINE | re.DOTALL)

_BRANCH = "pr-branch"
_SUBMODULE = "lib/plugin"

#: Local paths stand in for GitHub here, and git refuses `file://` submodule
#: transport by default since 2.38.1. Set through the environment so that it
#: reaches the clones git makes on a submodule's behalf, where `-c` does not.
_GIT_ENV = {
    "PATH": os.environ.get("PATH", ""),
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "protocol.file.allow",
    "GIT_CONFIG_VALUE_0": "always",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**_GIT_ENV, "HOME": str(cwd)},
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _bare(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "--bare", "--initial-branch=main")
    return path


def _a_change_that_bumps_a_submodule(root: Path) -> tuple[Path, str]:
    """A PR whose commit pins the submodule somewhere `main` does not.

    Returns the workspace clone, sitting on the default branch with its
    submodule populated as a fresh phase workspace arrives, plus the head
    under review.
    """
    sub_origin = _bare(root / "plugin.git")
    sub = root / "plugin"
    sub.mkdir()
    _git(sub, "init", "--initial-branch=main")
    _git(sub, "remote", "add", "origin", str(sub_origin))
    (sub / "plugin.txt").write_text("1\n")
    _git(sub, "add", "plugin.txt")
    _git(sub, "commit", "-m", "plugin 1")
    _git(sub, "push", "origin", "main")

    origin = _bare(root / "origin.git")
    author = root / "author"
    author.mkdir()
    _git(author, "init", "--initial-branch=main")
    _git(author, "remote", "add", "origin", str(origin))
    _git(author, "submodule", "add", str(sub_origin), _SUBMODULE)
    _git(author, "commit", "-m", "base")
    _git(author, "push", "origin", "main")

    (sub / "plugin.txt").write_text("2\n")
    _git(sub, "commit", "-am", "plugin 2")
    _git(sub, "push", "origin", "main")

    _git(author, "checkout", "-b", _BRANCH)
    _git(author / _SUBMODULE, "pull", "origin", "main")
    (author / "shipped.py").write_text("shipped = 2\n")
    _git(author, "add", "shipped.py", _SUBMODULE)
    _git(author, "commit", "-m", "the change under review, bumping the plugin")
    _git(author, "push", "origin", _BRANCH)
    head = _git(author, "rev-parse", "HEAD")

    # The guard's double maps the workspace's repos directory onto root/repos.
    workspace = root / "repos" / "syntropic137"
    workspace.mkdir(parents=True)
    _git(workspace, "clone", "--recurse-submodules", str(origin), ".")
    assert _git(workspace, "ls-tree", "HEAD", _SUBMODULE) != _git(
        workspace, "ls-tree", head, _SUBMODULE
    ), "the fixture must pin a different gitlink at the head than on main"
    return workspace, head


def _the_checkout(prompt: str, workflow: str, phase_id: str) -> str:
    blocks = [b for b in _FENCED_BLOCK.findall(prompt) if re.search(r"^git checkout", b, re.M)]
    assert len(blocks) == 1, (
        f"{workflow} '{phase_id}' has {len(blocks)} fenced blocks that run `git checkout`; "
        "this test runs the one that puts the reviewed commit on disk."
    )
    return str(blocks[0])


def _run(script: str, workspace: Path, head: str) -> None:
    """Run a checkout block with the values earlier phases would have recorded.

    The placeholder names differ between prompts; each is mapped to the value
    it means. One this table does not know is refused rather than guessed.
    """
    values = {
        "branch-from-the-artifact": _BRANCH,
        "the-exact-commit-SHA-from-the-artifact": head,
        "branch": _BRANCH,
        "candidate-sha": head,
        "pr-branch": _BRANCH,
        "recorded-head": head,
        # The pr-review prompts diff against the base they recorded. The
        # fixture's base is the default branch the workspace was cloned on.
        "recorded-base": _git(workspace, "rev-parse", "origin/main"),
    }
    for name, value in values.items():
        script = script.replace(f"<{name}>", value)
    leftover = sorted(set(re.findall(r"<[A-Za-z-]+>", script)))
    assert not leftover, f"the block names {leftover}, which this test cannot supply"
    done = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=workspace,
        env={**_GIT_ENV, "HOME": str(workspace.parent)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, f"the checkout block failed:\n{done.stdout}\n{done.stderr}"


@pytest.mark.parametrize(("workflow", "phase_id"), _REVIEW_PHASES)
async def test_a_review_checkout_leaves_nothing_for_the_guard(
    workflow: str, phase_id: str, tmp_path: Path
) -> None:
    workspace, head = _a_change_that_bumps_a_submodule(tmp_path)
    prompt = await _prompt_reaching_execution(workflow, phase_id)

    _run(_the_checkout(prompt, workflow, phase_id), workspace, head)

    assert _git(workspace, "rev-parse", "HEAD") == head
    # Teardown's own call, with the phase's own declaration. Raises
    # UnpushedWorkQuarantinedError if the checkout left the gitlink dirty.
    await quarantine_unpushed_work(
        _Workspace(tmp_path),
        execution_id="exec-5a22616362bd",
        phase_id=phase_id,
        delivers_repo_changes=False,
    )
