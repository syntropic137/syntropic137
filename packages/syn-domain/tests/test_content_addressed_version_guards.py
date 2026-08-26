"""CI safety test for content-addressed version guards.

Prevents the class of bug where a slice pins content by a ``sha256-<hash>``
version but never checks that the hash names the content it was given.

Such a version is a content commitment, not a label. Without the check a
caller registers arbitrary content under a version naming another tree's
hash, and every later install resolving that source/version/name triple
silently receives the substituted content.

``register_skill`` has enforced this since #772. ``register_claude_plugin``
pinned content the same way and did not, despite the correct pattern living
one directory over with a comment explaining exactly why it was needed. That
is the gap this test closes: not the missing guard in one slice, but the
absence of anything forcing the NEXT slice to carry it.

This test ENUMERATES rather than asserting per slice. A per-slice test only
covers the slices someone remembered to write one for; an enumerating test
fails when a new content-addressed slice is added without the guard, which is
the property that was missing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SLICES_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "syn_domain"
    / "contexts"
    / "orchestration"
    / "slices"
)

# A slice is content-addressed if it hashes the submitted tree itself.
_TREE_HASH_FN = "_compute_tree_sha"
_GUARD_FN = "_reject_hash_version_mismatch"
# The guard must precede the idempotency short-circuit: checking after it
# leaves the FIRST registration of a triple unguarded, and the first is the
# only one that matters, because every later resolve returns what it stored.
_FAST_PATH_CALL = "get_by_id"


def _content_addressed_handlers() -> list[Path]:
    """Every non-test slice module that hashes a submitted tree."""
    found: list[Path] = []
    for path in sorted(_SLICES_DIR.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        if _TREE_HASH_FN in path.read_text(encoding="utf-8"):
            found.append(path)
    return found


def _called_names(node: ast.AST) -> list[tuple[str, int]]:
    """(function name, line) for every call in a subtree, in source order."""
    calls: list[tuple[str, int]] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name):
            calls.append((func.id, sub.lineno))
        elif isinstance(func, ast.Attribute):
            calls.append((func.attr, sub.lineno))
    return sorted(calls, key=lambda c: c[1])


@pytest.mark.unit
def test_at_least_one_content_addressed_slice_is_discovered() -> None:
    """Guard the guard: a broken discovery would make every check below vacuous."""
    handlers = _content_addressed_handlers()
    assert handlers, (
        f"No slice module under {_SLICES_DIR} references {_TREE_HASH_FN!r}. "
        "Either the helper was renamed - update _TREE_HASH_FN - or this test "
        "is now checking nothing."
    )


@pytest.mark.unit
@pytest.mark.parametrize("handler_path", _content_addressed_handlers(), ids=lambda p: p.stem)
def test_content_addressed_slice_rejects_a_hash_version_mismatch(handler_path: Path) -> None:
    """Every slice that hashes a submitted tree must verify a declared hash."""
    source = handler_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert _GUARD_FN in defined, (
        f"{handler_path.name} hashes the submitted tree but defines no {_GUARD_FN!r}. "
        "A sha256- version is a content commitment: without this check a caller can "
        "register arbitrary content under a version naming another tree's hash, and "
        "every later install resolving that triple receives the substituted content. "
        "Mirror the implementation in register_skill rather than writing a new one."
    )


@pytest.mark.unit
@pytest.mark.parametrize("handler_path", _content_addressed_handlers(), ids=lambda p: p.stem)
def test_hash_guard_runs_before_the_idempotency_fast_path(handler_path: Path) -> None:
    """The guard must precede the existing-aggregate short-circuit.

    Checking afterwards leaves the first registration of a triple unguarded,
    which is the only one that decides what every later resolve returns.
    """
    tree = ast.parse(handler_path.read_text(encoding="utf-8"))

    handles = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "handle"
    ]
    assert handles, f"{handler_path.name} defines no handle(); adjust this test to match."

    for handle in handles:
        calls = _called_names(handle)
        guard_lines = [line for name, line in calls if name == _GUARD_FN]
        fast_path_lines = [line for name, line in calls if name == _FAST_PATH_CALL]

        assert guard_lines, (
            f"{handler_path.name}.handle() never calls {_GUARD_FN!r}. Defining it is "
            "not enough; it has to run."
        )
        if fast_path_lines:
            assert min(guard_lines) < min(fast_path_lines), (
                f"{handler_path.name}.handle() calls {_GUARD_FN!r} at line "
                f"{min(guard_lines)}, after {_FAST_PATH_CALL!r} at line "
                f"{min(fast_path_lines)}. The guard must come first, or the first "
                "registration of a source/version/name triple is never checked - and "
                "that is the one every later resolve returns."
            )
