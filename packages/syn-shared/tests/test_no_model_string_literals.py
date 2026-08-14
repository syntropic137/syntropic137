"""Poka-yoke for issue #793: model identifiers must not appear as bare literals.

Model names are domain values. Written inline they drift: the pricing table,
the CLI command builder, and the phase defaults each grew their own copy of
"haiku"/"sonnet"/"opus", and that is how a codex phase ended up priced as
Haiku in two places at once (#788).

Every model alias and canonical id now lives in ``syn_shared.agents``
(``ModelAlias`` / ``ModelId``) and is referenced from there. This test fails
if a new bare literal shows up in production code.

Scope note: this checks STRING LITERALS via the AST, so comments and
docstrings that mention a model by name are fine - it is the executable
value that must come from the enum.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from syn_shared.agents import ModelAlias, ModelId

# The repo root is four parents up from packages/syn-shared/tests/<file>.
_REPO_ROOT = Path(__file__).resolve().parents[3]

_SEARCH_ROOTS = (
    _REPO_ROOT / "packages" / "syn-domain" / "src",
    _REPO_ROOT / "packages" / "syn-shared" / "src",
    _REPO_ROOT / "packages" / "syn-adapters" / "src",
    _REPO_ROOT / "apps" / "syn-api" / "src",
)

# Where these values are ALLOWED to appear as literals: the enums that define
# them, and the pricing table's own alias map for CLI spellings that have no
# enum member (e.g. undated family names the CLI accepts).
_DEFINING_FILES = frozenset(
    {
        _REPO_ROOT / "packages" / "syn-shared" / "src" / "syn_shared" / "agents.py",
    }
)

_FORBIDDEN = frozenset({str(m) for m in ModelAlias} | {str(m) for m in ModelId})


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Ids of string constants that are docstrings or bare string expressions."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
                skip.add(id(child.value))
    return skip


def _bare_model_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in skip:
            continue
        if isinstance(node.value, str) and node.value in _FORBIDDEN:
            found.append((node.lineno, node.value))
    return found


def _production_files() -> list[Path]:
    files: list[Path] = []
    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        files.extend(
            path
            for path in root.rglob("*.py")
            if path not in _DEFINING_FILES and not path.name.startswith("test_")
        )
    return sorted(files)


@pytest.mark.unit
def test_no_bare_model_literals_in_production_code() -> None:
    """A model name written inline is a bug waiting to diverge - use the enum."""
    offenders: list[str] = []
    for path in _production_files():
        for lineno, literal in _bare_model_literals(path):
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno} -> {literal!r}")

    assert not offenders, (
        "Bare model-name literals found. Import ModelAlias / ModelId from "
        "syn_shared.agents instead (issue #793):\n  " + "\n  ".join(offenders)
    )


@pytest.mark.unit
def test_every_model_id_has_a_price() -> None:
    """A ModelId with no pricing entry would silently fall through to unpriced."""
    from syn_shared.pricing import MODEL_PRICING_TABLE

    missing = [model for model in ModelId if model not in MODEL_PRICING_TABLE]

    assert not missing, f"ModelId members with no pricing entry: {missing}"
