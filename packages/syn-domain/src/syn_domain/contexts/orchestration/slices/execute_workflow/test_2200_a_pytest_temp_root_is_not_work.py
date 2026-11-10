"""pytest's temp root in a repository is not work; anything beside it still is (#2200).

THE INCIDENT. On exec-17dfad720619 a phase ran its tests with TMPDIR inside
the checkout, pushed everything, and was failed by the gate for one line of
``status --porcelain``: ``?? pytest-of-agent/``. Nothing in it was the
phase's; pytest writes and rotates that tree itself.

These run REAL git against REAL repositories through the gate, and build the
tree the way pytest does: numbered run dirs and a ``pytest-current`` symlink.
The exemption only ever weakens the gate, so three of the four are about what
it must NOT let through.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    UnpushedWorkQuarantinedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _Clone,
    _clone_repository,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_TEMP_ROOT = "pytest-of-agent"


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A pushed-up-to-date clone holding the tree pytest leaves, and nothing else."""
    repo = _clone_repository(tmp_path)
    root = repo.path / _TEMP_ROOT
    for run in ("pytest-0", "pytest-1"):
        case = root / run / "test_something0"
        case.mkdir(parents=True)
        (case / "fixture.txt").write_text("written by a test\n")
    (root / "pytest-current").symlink_to(root / "pytest-1")
    assert repo.git("status", "--porcelain") == f"?? {_TEMP_ROOT}/", (
        "the fixture must reproduce the incident's single porcelain line"
    )
    return repo


async def test_a_tree_only_pytest_wrote_is_left_and_named(
    clone: _Clone, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        await clone.run_gate()

    assert not [ref for ref in clone.origin_refs() if ref.startswith("refs/syn/lost/")]
    assert any(
        "pytest temp root" in record.getMessage() and _TEMP_ROOT in record.getMessage()
        for record in caplog.records
    ), "the tree was left out without saying so"


async def test_a_source_file_beside_it_is_still_work(clone: _Clone) -> None:
    (clone.path / "new_module.py").write_text("an agent wrote this\n")

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await clone.run_gate()

    assert "new_module.py" in str(raised.value)


async def test_a_file_pytest_would_not_write_there_keeps_the_tree(clone: _Clone) -> None:
    (clone.path / _TEMP_ROOT / "notes.md").write_text("an agent hid this here\n")

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await clone.run_gate()

    assert _TEMP_ROOT in str(raised.value)


async def test_a_tracked_change_beside_it_is_still_work(clone: _Clone) -> None:
    (clone.path / "README.md").write_text("edited but never committed\n")

    with pytest.raises(UnpushedWorkQuarantinedError) as raised:
        await clone.run_gate()

    assert "README.md" in str(raised.value)
