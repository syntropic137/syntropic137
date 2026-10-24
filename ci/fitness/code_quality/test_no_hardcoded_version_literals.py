"""Fitness function: no release number is written into Python source (#1389).

A version with two homes drifts the first time a bump misses one, and then a
reported version is not evidence of what is running (#1380): the release
number has ONE owner, the package manifest, read through installed metadata.
Rejected: a module-scope ``__version__`` bound to a string literal, and a
literal ``version=`` passed to ``fastapi.FastAPI`` or a subclass, resolved
through imports, renames and subclassing. The detector is
``scripts/check_version_literals.py``, pinned by
``scripts/tests/test_check_version_literals.py``.

Scope: every tracked ``*.py`` in this repo AND in each checked-out submodule
(``git ls-files --recurse-submodules``), test files excluded. Submodule code
cannot be fixed here, so its known violations are exact-count entries in
``[hardcoded_version_literals]`` of ``fitness_exceptions.toml``, each naming an
issue. Only paths inside a submodule may be listed. An entry whose count is
above what the scan finds, or whose file is gone from a checked-out submodule,
fails as stale, so the table only shrinks.

Principle: 1. Single Ownership (docs/architecture/architectural-fitness.md)
Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from ci.fitness.conftest import load_exceptions, repo_root

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from check_version_literals import (
    ExceptionEntry,
    exception_problems,
    scan,
    submodules,
)

_SECTION = "hardcoded_version_literals"


def _entries() -> dict[str, ExceptionEntry]:
    raw: dict[str, dict[str, str | int]] = load_exceptions(repo_root()).get(_SECTION, {})
    return {
        rel: ExceptionEntry(count=int(row.get("count", 0)), issue=str(row.get("issue", "")))
        for rel, row in raw.items()
    }


@pytest.mark.architecture
class TestNoHardcodedVersionLiterals:
    def test_no_release_number_is_written_into_source(self) -> None:
        entries = _entries()
        over = {
            rel: hits
            for rel, hits in scan(repo_root()).items()
            if len(hits) > (entries[rel].count if rel in entries else 0)
        }
        if over:
            pytest.fail(
                "Hardcoded release number (#1389). Read it from importlib.metadata "
                "(see syn_collector.collector.version), or delete a __version__ nothing "
                "reads:\n"
                + "\n".join(
                    f"  {rel}:{hit.line}: {hit.shape}" for rel, hits in over.items() for hit in hits
                )
            )

    def test_exceptions_are_submodule_only_explained_and_not_stale(self) -> None:
        root = repo_root()
        found = {rel: len(hits) for rel, hits in scan(root).items()}
        problems = exception_problems(
            _entries(), found, submodules(root), lambda rel: (root / rel).is_file()
        )
        if problems:
            pytest.fail(
                f"[{_SECTION}] in ci/fitness/fitness_exceptions.toml:\n  " + "\n  ".join(problems)
            )
