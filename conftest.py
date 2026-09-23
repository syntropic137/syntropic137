"""Pytest configuration for all tests in the Syntropic137 project.

Sets APP_ENVIRONMENT=test to ensure in-memory storage is used during testing.

Test Infrastructure (ADR-034):
    - test_infrastructure: Auto-detects test-stack or uses testcontainers
    - db_pool: Database connection pool
"""

from __future__ import annotations

import os

# Set test environment BEFORE any imports that might read settings
os.environ["APP_ENVIRONMENT"] = "test"


import pytest

from syn_adapters.storage import reset_storage

# Git exports these to hooks, and they override a subprocess's cwd. Under the
# pre-push hook, a test that runs `git init`/`commit` in a tmp dir would
# otherwise write into the real repository: it did, committing onto the pushing
# branch and the shared local `main`. The list is `git rev-parse
# --local-env-vars` (git 2.50), which git's hook docs say to clear before
# operating on another repository, plus the numbered GIT_CONFIG_KEY_/VALUE_
# pairs that GIT_CONFIG_COUNT indexes. Repository discovery from cwd still finds
# the real repo for tests that mean to read it.
_GIT_LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)
for _var in list(os.environ):
    if _var in _GIT_LOCAL_ENV_VARS or _var.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
        os.environ.pop(_var, None)

# Register test infrastructure fixtures (ADR-034)
pytest_plugins = [
    "syn_tests.fixtures.infrastructure",
]


@pytest.fixture(autouse=True)
def reset_storage_between_tests() -> None:
    """Reset all storage before each test for isolation."""
    reset_storage()
