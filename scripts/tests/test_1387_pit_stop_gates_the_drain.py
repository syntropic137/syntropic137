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
