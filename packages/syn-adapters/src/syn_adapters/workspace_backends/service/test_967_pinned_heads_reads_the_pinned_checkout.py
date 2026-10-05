"""`pinned_heads` reads back exactly what `append_pinned_checkout` wrote (#967).

The in-memory workspace answers `rev-parse HEAD` from it, so a drift between
the writer and the reader would make that double report a checkout no script
performed - or none at all, failing every pinned run that uses it.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.service.pinned_checkout import (
    append_pinned_checkout,
    pinned_heads,
)

pytestmark = pytest.mark.unit

DETACHED = "967c0000000000000000000000000000000000c1"
CONTINUED = "967d0000000000000000000000000000000000d2"


def test_both_checkout_variants_are_read_back_by_destination() -> None:
    lines: list[str] = ["git clone https://github.com/o/app /workspace/repos/app"]
    append_pinned_checkout(lines, repository="o/app", dest="/workspace/repos/app", sha=DETACHED)
    append_pinned_checkout(
        lines, repository="o/lib", dest="/workspace/repos/lib", sha=CONTINUED, branch="fix/x"
    )

    assert pinned_heads("\n".join(lines)) == {
        "/workspace/repos/app": DETACHED,
        "/workspace/repos/lib": CONTINUED,
    }


def test_a_script_with_no_pin_has_no_heads() -> None:
    assert pinned_heads("git clone https://github.com/o/app /workspace/repos/app") == {}
