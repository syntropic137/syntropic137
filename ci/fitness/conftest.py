"""Shared fixtures and helpers for architectural fitness functions.

See ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md).

RUNNING THE GATES MUST NOT MODIFY THE REPOSITORY (#1343)
=======================================================

Several gates shell out to git, and some of them build git fixtures - commits,
branches, checkouts - which only make sense inside a throwaway repository under
`tmp_path`. Naming that repository at the call site, with `-C` or `cwd=`, is not
enough to keep them there: git locates a repository from its *environment*
first, and `GIT_DIR` beats both. So a `git commit` aimed at a temp directory
lands in whatever repository `GIT_DIR` names, while the working-tree file it
just wrote stays in the temp directory - the objects and the refs go one way,
the files the other.

That is not hypothetical. git exports `GIT_DIR` to every hook it runs from a
worktree, `.githooks/pre-push` runs `just preflight`, and preflight runs this
suite; the fixtures then committed into the developer's own checkout and
force-moved its branches, `main` included, while the run reported green. One
`.git` backs every worktree, so moving `main` moved it for all of them, and the
next `git push origin main` would have pushed a commit named `merged-pointer`.

`_forget_the_ambient_repository` is how that is answered, once, for the whole
suite rather than at each call site: a call site can only be as careful as the
person who wrote it remembered to be, and the failure is silent. Afterwards
every git subprocess - present, and any a later gate adds - resolves the
repository from the directory it was given, which is what every call site here
already believes is happening.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest


def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parents[2]


_PRODUCTION_DIRS = ["apps/*/src", "packages/*/src"]
_EXCLUDED_NAMES = {"conftest.py", "__init__.py"}


def production_files(root: Path | None = None) -> list[Path]:
    """Yield all production .py files under apps/*/src and packages/*/src."""
    root = root or repo_root()
    files: list[Path] = []
    for pattern in _PRODUCTION_DIRS:
        for py_file in root.glob(f"{pattern}/**/*.py"):
            if py_file.name in _EXCLUDED_NAMES:
                continue
            if py_file.name.startswith("test_"):
                continue
            files.append(py_file)
    return sorted(files)


def load_exceptions(root: Path | None = None) -> dict[str, Any]:
    """Load fitness_exceptions.toml from the ci/fitness directory."""
    root = root or repo_root()
    toml_path = root / "ci" / "fitness" / "fitness_exceptions.toml"
    if not toml_path.exists():
        return {}
    with toml_path.open("rb") as f:
        return tomllib.load(f)


def rel_path(path: Path, root: Path | None = None) -> str:
    """Return a path relative to repo root for use as exception keys."""
    root = root or repo_root()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


#: The variables that redirect where git thinks a repository is, regardless of
#: the directory a command is given. git's own docs group them as the ones that
#: "control repository location"; a hook inherits the first three from the
#: worktree it fired in, and the rest are here because any of them alone is
#: enough to make a command address a repository the caller never named.
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

    Removing them from this process is what reaches the subprocesses, since
    `subprocess.run` inherits `os.environ` by default - and it is why this is
    not a fixture. Collection imports test modules, and a module that asks git
    something while being imported would run before any fixture could.

    Credential, transport and identity variables are deliberately left alone:
    they say how to reach a remote, not which repository is the local one, and
    the reachability gate genuinely needs them. Nothing is restored afterwards,
    because there is no later point in this process at which a git command
    should start meaning the ambient repository again.
    """
    for var in _REPOSITORY_LOCATION_VARS:
        os.environ.pop(var, None)


def pytest_configure(config: pytest.Config) -> None:
    _forget_the_ambient_repository()
    config.addinivalue_line(
        "markers",
        "architecture: Architectural fitness functions (CI-enforced structural checks)",
    )
