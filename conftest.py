"""Pytest configuration for all tests in the Syntropic137 project.

Sets APP_ENVIRONMENT=test to ensure in-memory storage is used during testing.

Test Infrastructure (ADR-034):
    - test_infrastructure: Auto-detects test-stack or uses testcontainers
    - db_pool: Database connection pool

No test may modify the repository it is run from (#1343):
    - _forget_the_ambient_repository: git fixtures stay in their tmp_path
"""

from __future__ import annotations

import os

# Set test environment BEFORE any imports that might read settings
os.environ["APP_ENVIRONMENT"] = "test"

import pytest

from syn_adapters.storage import reset_storage

#: The variables that decide which repository a git command operates on,
#: whatever directory the command is given. git's own docs group them as the
#: ones that control repository location; a hook inherits the first three from
#: the worktree it fired in, and any one of them alone is enough to send a
#: command somewhere the caller never named.
_REPOSITORY_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_PREFIX",
)


def _forget_the_ambient_repository() -> None:
    """Make every git subprocess in this run address the directory it is given.

    Tests across this repository build git fixtures - `init`, `commit`,
    `checkout -b` - in a `tmp_path`, and name that directory with `-C` or
    `cwd=`. Neither is enough on its own: git resolves `GIT_DIR` from the
    environment before it looks at either, so with one inherited, the objects
    and refs go to the repository `GIT_DIR` names while the files the fixture
    writes stay in the temp directory.

    That is how #1343 arrived. git exports `GIT_DIR` to every hook it runs from
    a worktree, `.githooks/pre-push` runs `just preflight`, and preflight runs
    the fitness suite; its fixtures then committed into the developer's own
    checkout and force-moved its branches, `main` included, while the run
    reported green. One `.git` backs every worktree, so `main` moved for all of
    them, and the next `git push origin main` would have pushed a commit named
    `merged-pointer`.

    Answered here, once, rather than at each call site, because a call site can
    only be as careful as its author remembered to be and the failure is
    silent - and at import rather than in a fixture, because collection imports
    modules that ask git things before any fixture could run.

    Credential, transport and identity variables are deliberately left alone:
    they say how to reach a remote, not which repository is the local one, and
    the submodule-reachability gate genuinely needs them. Nothing is restored
    afterwards, because there is no later point in a test run at which a git
    command should start meaning the ambient repository again.

    `ci/fitness/test_the_gates_leave_the_repository_alone.py` is what holds this.
    """
    for var in _REPOSITORY_LOCATION_VARS:
        os.environ.pop(var, None)


_forget_the_ambient_repository()

# Register test infrastructure fixtures (ADR-034)
pytest_plugins = [
    "syn_tests.fixtures.infrastructure",
]


@pytest.fixture(autouse=True)
def reset_storage_between_tests() -> None:
    """Reset all storage before each test for isolation."""
    reset_storage()
