"""The deploy script's gate has to be in the right ORDER (#1387).

The flag is only worth having if the deploy sets it before it looks at the
drain and clears it after the swap is verified. Both ends fail quietly if they
move:

* pausing AFTER the drain check leaves exactly the window the issue is about -
  the drain reports a quiet system, then a webhook admits work, then the
  container is recreated under it;
* clearing BEFORE the swap re-opens admission to the container that is about
  to be killed, which is the same lost execution one stage later.

Neither shows up in a successful deploy. So this reads the script and asserts
the order of the four stages, which is the only property that distinguishes a
gate from a pause that happens to be in the file.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pit_stop.sh"

#: Each stage, identified by a line that only that stage contains.
_PAUSE = 'maintenance true "pit stop $VERSION"'
_DRAIN = "until drained; do"
_SWAP = "docker compose -f $COMPOSE up -d api gateway"
_VERIFY = 'die "projections not healthy after the swap"'
_RESUME = 'step "gate: resuming execution admission"'
_STAGE_ONLY_EXIT = 'step "staged $TAG; run with --swap-only once drained"'


def _line_of(needle: str) -> int:
    lines = _SCRIPT.read_text().splitlines()
    hits = [i for i, line in enumerate(lines) if needle in line]
    assert len(hits) == 1, (
        f"expected exactly one line containing {needle!r} in {_SCRIPT.name}, found {len(hits)}. "
        f"This test identifies stages by these lines; if one moved or was "
        f"duplicated, the order below is no longer being checked."
    )
    return hits[0]


class TestTheOrderOfTheStages:
    def test_admission_is_paused_before_the_drain_is_believed(self) -> None:
        assert _line_of(_PAUSE) < _line_of(_DRAIN)

    def test_admission_is_paused_before_the_swap(self) -> None:
        assert _line_of(_PAUSE) < _line_of(_SWAP)

    def test_admission_resumes_only_after_the_swap(self) -> None:
        assert _line_of(_SWAP) < _line_of(_RESUME)

    def test_admission_resumes_only_after_verify(self) -> None:
        """A deploy that swapped but failed verify should stay shut: the new
        container is unconfirmed, and refusing is the recoverable answer."""
        assert _line_of(_VERIFY) < _line_of(_RESUME)


class TestStagingAloneChangesNothing:
    """`--stage-only` is documented as safe while runs are in flight. Pausing
    admission there would make it the opposite of safe."""

    def test_stage_only_returns_before_the_gate(self) -> None:
        assert _line_of(_STAGE_ONLY_EXIT) < _line_of(_PAUSE)


_VERSION_CHECK = 'die "GET /version failed after the swap"'
_BUMP_COMMIT = 'commit --no-verify -q -m "chore: bump to $VERSION"'
_BUILT_SHA = 'BUILT_SHA="$(git -C "$WT" rev-parse --verify HEAD)"'


class TestTheShippedBuildIdentifiesItself:
    """#1473: the image carries the commit it was built from, and verify reads
    it back before admission reopens."""

    def test_identity_is_checked_before_admission_resumes(self) -> None:
        assert _line_of(_VERSION_CHECK) < _line_of(_RESUME)

    def test_the_stamped_commit_is_the_bump_commit_not_the_base_ref(self) -> None:
        """bump-version rewrites the package metadata syn-api reads its release
        from, so $REF's tree is not the tree that ships. The SHA must be read
        from the worktree after the bump is committed."""
        assert _line_of(_BUMP_COMMIT) < _line_of(_BUILT_SHA)
        script = _SCRIPT.read_text()
        assert '--build-arg SYN_BUILD_COMMIT="$BUILT_SHA"' in script
        assert 'BUILT_SHA="$(git -C "$REPO_TOP" rev-parse' not in script


def _version_check_program() -> str:
    """The python the verify stage runs against GET /version."""
    script = _SCRIPT.read_text()
    start = script.index("<<'PY' || die \"the running API does not report the build just shipped")
    body_start = script.index("\n", start) + 1
    return script[body_start : script.index("\nPY\n", body_start)]


@pytest.mark.parametrize(
    ("label", "body", "tag", "sha", "passes"),
    [
        ("the build just shipped", {"image_tag": "v1.2.0", "commit": "abc"}, "v1.2.0", "abc", True),
        ("another commit", {"image_tag": "v1.2.0", "commit": "def"}, "v1.2.0", "abc", False),
        ("another tag", {"image_tag": "v1.1.0", "commit": "abc"}, "v1.2.0", "abc", False),
        ("an unstamped image", {"image_tag": None, "commit": None}, "v1.2.0", "abc", False),
        ("--swap-only, stamped", {"image_tag": "v1.2.0", "commit": "abc"}, "v1.2.0", "", True),
        ("--swap-only, no commit", {"image_tag": "v1.2.0", "commit": None}, "v1.2.0", "", False),
    ],
)
def test_the_version_check_accepts_only_the_build_just_shipped(
    tmp_path: Path, label: str, body: dict[str, str | None], tag: str, sha: str, passes: bool
) -> None:
    payload = tmp_path / "version.json"
    payload.write_text(json.dumps(body))
    result = subprocess.run(
        [sys.executable, "-", str(payload), tag, sha],
        input=_version_check_program(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is passes, f"{label}: {result.stdout}{result.stderr}"
