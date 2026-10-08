"""A branch creation names no commit, so it is never an Own Push (PC-128).

Round 3's blocking reproduction, driven through real git: a quiet push of an
unrelated ref runs the pre-push hook, which reads the checked-out branch at a
foreign SHA, and git prints nothing for it. HEAD then changes and a
`--no-verify` push creates the branch from it, printing the only status table
in the tool result - one hookless `* [new branch] HEAD -> <branch>` that no
output can tell apart from the hooked push's own. Attributing the hook's SHA to
it continued the foreign commit as this run's own.

The output here is what git itself prints, run in a throwaway repository with
a pre-push hook that prints the workspace hook's `git_push` line. Everything
after the tool result is the production path the sibling PC-128 tests drive.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.events.PhaseCommitPushedEvent import (
    PhaseCommitPushedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    OWN_UNVERIFIED_PUSH,
)
from syn_domain.contexts.orchestration.slices.start_resume.test_pc128_a_resume_reverifies_its_own_pushes import (
    BRANCH,
    PARENT,
    REPO,
    VERIFIED,
    _orphaned_mid_fix,
    _resume,
    _Store,
    _told,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: The workspace hook's `git_push` line, as `_hook_line` in the sibling test
#: writes it, read from the checked-out branch and HEAD the way the real hook
#: reads them.
_HOOK = f"""#!{sys.executable}
import json, subprocess, sys

def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()

print(json.dumps({{
    "event_type": "git_push",
    "timestamp": "2026-10-08T01:00:00+00:00",
    "session_id": "sess-pc128",
    "provider": "claude",
    "context": {{"git": {{
        "operation": "push",
        "remote": sys.argv[1],
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "sha": git("rev-parse", "HEAD"),
        "repo": "widgets",
        "commits_count": 1,
    }}}},
    "metadata": None,
}}), file=sys.stderr)
"""


class _Clone:
    """A clone of a bare `widgets.git`, with the hook installed, isolated from user config."""

    def __init__(self, root: Path) -> None:
        self.dir = root / "work"
        remote = root / "widgets.git"
        self._env = {
            **os.environ,
            "HOME": str(root),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "pc128",
            "GIT_AUTHOR_EMAIL": "pc128@example.invalid",
            "GIT_COMMITTER_NAME": "pc128",
            "GIT_COMMITTER_EMAIL": "pc128@example.invalid",
        }
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=self._env)
        self.dir.mkdir()
        self.shell(f"git init -q -b main && git remote add origin {remote}")
        hook = self.dir / ".git" / "hooks" / "pre-push"
        hook.write_text(_HOOK)
        hook.chmod(0o755)
        self.commit("base")
        self.shell("git push -q --no-verify origin HEAD:refs/heads/main")

    def shell(self, script: str) -> str:
        """Run ``script`` as the agent's Bash tool would: stdout and stderr in one result."""
        done = subprocess.run(
            ["bash", "-c", f"set -e; {script}"],
            cwd=self.dir,
            env=self._env,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout + done.stderr

    def commit(self, message: str) -> str:
        self.shell(f"git commit -q --allow-empty -m {message}")
        return self.shell("git rev-parse HEAD").strip()


def _recorded(store: _Store) -> list[str]:
    return [
        e.event.sha for e in store.events[PARENT] if isinstance(e.event, PhaseCommitPushedEvent)
    ]


class TestAHooklessCreationAfterAQuietPushClaimsNothing:
    async def test_the_foreign_sha_the_quiet_push_hook_read_is_not_recorded_or_continued(
        self, tmp_path: Path
    ) -> None:
        clone = _Clone(tmp_path)
        foreign = clone.commit("foreign")
        clone.shell(f"git checkout -q -b {BRANCH}")
        own = clone.commit("own")
        # Checked out on BRANCH at the foreign SHA, as after fetching someone else's head.
        clone.shell(f"git reset -q --hard {foreign}")

        tool_result = clone.shell(
            "git push -q origin HEAD:refs/heads/unrelated; "
            f"git checkout -q --detach {own}; "
            f"git push --no-verify origin HEAD:refs/heads/{BRANCH}"
        )
        # The shape round 3 blocked on: one hook line naming BRANCH at the
        # foreign SHA, then the only status table, a hookless creation.
        [hook] = [line for line in tool_result.splitlines() if line.startswith("{")]
        assert json.loads(hook)["context"]["git"] == {
            "operation": "push",
            "remote": "origin",
            "branch": BRANCH,
            "sha": foreign,
            "repo": "widgets",
            "commits_count": 1,
        }
        assert f"* [new branch]      HEAD -> {BRANCH}" in tool_result

        store = _Store()
        await _orphaned_mid_fix(store, outputs=(tool_result,))

        assert foreign not in _recorded(store)
        pins = await _resume(store, forge_head=foreign)
        checkout = pins.checkout_for("fix")
        assert pins.continued_branches == []
        assert REPO not in checkout.branches
        assert checkout.commits[REPO] == VERIFIED
        assert OWN_UNVERIFIED_PUSH not in _told(pins)


class TestAnOwnUpdateIsStillContinued:
    async def test_a_hooked_push_that_updates_the_branch_to_head_is_the_runs_own(
        self, tmp_path: Path
    ) -> None:
        clone = _Clone(tmp_path)
        clone.shell(f"git checkout -q -b {BRANCH}")
        clone.commit("first")
        created = clone.shell(f"git push origin {BRANCH}")
        last = clone.commit("last")
        updated = clone.shell(f"git push origin {BRANCH}")
        assert f"{last[:7]}  {BRANCH} -> {BRANCH}" in updated

        store = _Store()
        await _orphaned_mid_fix(store, outputs=(created, updated))

        assert _recorded(store) == [last]
        pins = await _resume(store, forge_head=last)
        checkout = pins.checkout_for("fix")
        assert checkout.commits[REPO] == last
        assert checkout.branches[REPO] == BRANCH
        assert pins.abandoned_branches == []
        told = _told(pins)
        assert OWN_UNVERIFIED_PUSH in told
        assert last in told
