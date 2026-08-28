"""CI and the local gate must run the same checks (#931).

The two were assembled from independent lists and drifted: three checks were
reachable from no local recipe at all, the pre-push hook ran only the THRESHOLD
half of fitness, and a stale generated file could reach CI unnoticed. One push
hit three of those at once.

This makes the drift mechanically impossible to reintroduce: any `just` target
CI invokes must be inside `preflight`'s dependency closure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).resolve().parents[3]
_JUSTFILE = _ROOT / "justfile"
_WORKFLOWS = _ROOT / ".github" / "workflows"

#: Targets CI may run outside preflight, each with a reason it cannot be a
#: pre-push gate. Anything not listed here has to be in the closure.
_ALLOWED_OUTSIDE: dict[str, str] = {
    "codegen": "preflight runs codegen-check, which invokes it and diffs the result",
}


def _direct_deps(target: str, text: str) -> list[str]:
    match = re.search(rf"^{re.escape(target)}:([^\n]*)", text, re.MULTILINE)
    return match.group(1).split() if match else []


def _closure(root: str, text: str) -> set[str]:
    seen: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(_direct_deps(current, text))
    return seen


def _ci_just_targets() -> set[str]:
    found: set[str] = set()
    for workflow in _WORKFLOWS.glob("*.y*ml"):
        for name in re.findall(r"just ([a-z][a-z0-9:-]*)", workflow.read_text()):
            found.add(name)
    return found


def test_preflight_exists() -> None:
    assert _direct_deps("preflight", _JUSTFILE.read_text()), (
        "`preflight` must exist and name the gates; it is the single list "
        "CI, the pre-push hook and AGENTS.md all point at"
    )


def test_every_ci_check_is_reachable_from_preflight() -> None:
    text = _JUSTFILE.read_text()
    covered = _closure("preflight", text)
    missing = sorted(t for t in _ci_just_targets() if t not in covered and t not in _ALLOWED_OUTSIDE)

    assert not missing, (
        "CI runs `just` targets that `preflight` does not, so they cannot fail "
        f"before a push: {missing}. Add them to `preflight` in the justfile, or "
        "record why they cannot be local gates in _ALLOWED_OUTSIDE."
    )


def test_the_pre_push_hook_delegates_rather_than_listing_its_own_checks() -> None:
    """A hook carrying its own list is how the drift started."""
    hook = _ROOT / ".githooks" / "pre-push"
    if not hook.exists():
        pytest.skip("no pre-push hook in this checkout")
    assert "just preflight" in hook.read_text(), (
        "the pre-push hook must call `just preflight` rather than enumerate checks"
    )
