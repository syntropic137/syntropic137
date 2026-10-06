"""Image publishing recipes stay in the one justfile CODEOWNERS owns.

The recipes that build, push, re-tag and upload release images live in
`just/release.just`, which CODEOWNERS owns, so the root justfile does not have
to be (a routine recipe change should not wait on the owner). That split only
protects anything while three things hold, and each is a one-line edit to the
UNOWNED root justfile:

  * the root justfile still imports `just/release.just`;
  * no release recipe is (re)defined anywhere else;
  * duplicate recipes and variables stay forbidden. just refuses a second
    definition by default, but `set allow-duplicate-recipes` makes the later one
    win silently -- a release recipe overridden from an unowned file.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.architecture]

_ROOT = Path(__file__).resolve().parents[3]
_JUSTFILE = _ROOT / "justfile"
_RELEASE = _ROOT / "just" / "release.just"

#: Every recipe and variable that publishes or verifies a release image.
_RELEASE_NAMES = (
    "registry",
    "release-local",
    "verify-image-capabilities",
    "release-retag",
    "release-assets",
    "release-local-full",
)


def _defines(text: str, name: str) -> bool:
    """A recipe (`name ...:`) or variable (`name :=`) definition at column 0."""
    return re.search(rf"^{re.escape(name)}(\s[^\n]*)?:", text, re.MULTILINE) is not None


def _just_sources() -> list[Path]:
    return [_JUSTFILE, *sorted((_ROOT / "just").glob("*.just"))]


def test_the_root_justfile_imports_the_release_recipes() -> None:
    text = _JUSTFILE.read_text()
    assert re.search(r"^import\s+'just/release\.just'\s*$", text, re.MULTILINE), (
        "the justfile no longer imports just/release.just, so the release recipes vanish"
    )


@pytest.mark.parametrize("name", _RELEASE_NAMES)
def test_release_names_are_defined_only_in_the_owned_file(name: str) -> None:
    where = [
        path.relative_to(_ROOT).as_posix()
        for path in _just_sources()
        if _defines(path.read_text(), name)
    ]
    assert where == ["just/release.just"], (
        f"`{name}` is defined in {where}; it must be defined once, in just/release.just "
        "(CODEOWNERS-owned)"
    )


def test_duplicate_definitions_stay_forbidden() -> None:
    for path in _just_sources():
        text = path.read_text()
        assert not re.search(r"^set\s+allow-duplicate-(recipes|variables)", text, re.MULTILINE), (
            f"{path.relative_to(_ROOT)} allows duplicates, so an unowned file could "
            "override a release recipe"
        )


def test_the_definition_check_can_fail() -> None:
    """Negative control: a recipe signature with parameters is recognised."""
    assert _defines("release-local version:\n    echo\n", "release-local")
    assert _defines('registry := "x"\n', "registry")
    assert not _defines("    just release-local x\n", "release-local")
