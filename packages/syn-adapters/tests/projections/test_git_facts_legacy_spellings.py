"""The git facts a timeline row shows, read from every spelling a payload uses.

`GitFacts` reads four facts out of two payload shapes, and a legacy payload
spells each of them several ways. Nothing downstream can tell which spelling
arrived - the ToolOperation carries one `git_sha`, not four candidates - so a
spelling silently dropped from the chain is invisible everywhere except the
dashboard, months later, as a blank column.

These drive the CONSUMER (`to_operation`, the dispatch the TimescaleDB reader
and the in-memory timeline share), not `GitFacts` directly, and every fixture
below uses only the deep spellings: no legacy payload here sets `sha`,
`message` or `branch` at the top level, so none of these assertions can pass on
an implementation that reads the obvious key and stops.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projections.session_tools_dispatch import to_operation
from syn_shared.events import GIT_COMMIT, GIT_MERGE, GIT_OPERATION

if TYPE_CHECKING:
    from syn_adapters.projections.session_tools import ToolOperation

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
_GIT_TYPES = (GIT_COMMIT, GIT_MERGE, GIT_OPERATION)


def _convert(event_type: str, **payload: object) -> ToolOperation:
    """Convert one recorded observation the way the timeline reader does."""
    op = to_operation(_WHEN, payload, event_type, set(), _GIT_TYPES)
    assert op is not None, "a git observation must reach the timeline"
    return op


@pytest.mark.unit
def test_legacy_sha_is_read_from_merge_sha_when_that_is_the_only_spelling() -> None:
    op = _convert(GIT_MERGE, operation="merge", merge_sha="9f1c0de")
    assert op.git_sha == "9f1c0de"


@pytest.mark.unit
def test_legacy_sha_is_read_from_the_context_sub_object() -> None:
    op = _convert(GIT_COMMIT, operation="commit", context={"sha": "ab12cd3"})
    assert op.git_sha == "ab12cd3"


@pytest.mark.unit
def test_legacy_message_is_read_from_message_preview() -> None:
    op = _convert(
        GIT_COMMIT, operation="commit", message_preview="fix: the last spelling in the chain"
    )
    assert op.git_message == "fix: the last spelling in the chain"


@pytest.mark.unit
def test_legacy_message_is_read_from_commit_message() -> None:
    """The engine renames `message` to `commit_message` during ingestion."""
    op = _convert(GIT_COMMIT, operation="commit", commit_message="feat: renamed on the way in")
    assert op.git_message == "feat: renamed on the way in"


@pytest.mark.unit
def test_legacy_branch_is_read_from_to_branch() -> None:
    op = _convert(GIT_MERGE, operation="merge", to_branch="release")
    assert op.git_branch == "release"


@pytest.mark.unit
def test_legacy_branch_is_parsed_out_of_a_checkout_command_line() -> None:
    """A `git_operation` names no branch key at all - only the command it ran."""
    op = _convert(GIT_OPERATION, operation="checkout", command="git checkout -b fix/1034")
    assert op.git_branch == "fix/1034"


@pytest.mark.unit
def test_a_checkout_command_is_only_consulted_for_git_operation() -> None:
    """Every other event type leaves the branch unknown rather than guessing."""
    op = _convert(GIT_COMMIT, operation="commit", command="git checkout -b fix/1034")
    assert op.git_branch is None


@pytest.mark.unit
def test_legacy_repo_is_read_from_the_context_sub_object() -> None:
    op = _convert(GIT_COMMIT, operation="commit", context={"repo": "syntropic137"})
    assert op.git_repo == "syntropic137"


@pytest.mark.unit
def test_a_legacy_payload_reports_no_structured_git_object() -> None:
    """`git_data` is the v2 sub-object verbatim; inventing one for a legacy
    payload would report a shape that was never recorded."""
    op = _convert(GIT_COMMIT, operation="commit", commit_hash="deadbee")
    assert op.git_sha == "deadbee"
    assert op.git_data is None


@pytest.mark.unit
def test_a_v2_payload_falls_back_to_to_branch_and_passes_the_object_through() -> None:
    git = {"operation": "merge", "to_branch": "main", "sha": "0badc0d"}
    op = _convert(GIT_MERGE, git=git)
    assert op.git_branch == "main"
    assert op.git_sha == "0badc0d"
    assert op.git_data == git


@pytest.mark.unit
def test_an_empty_spelling_does_not_win_over_a_later_populated_one() -> None:
    """`""` is an absent fact, not an answer - the chain must keep looking."""
    op = _convert(
        GIT_COMMIT, operation="commit", sha="", context={"sha": ""}, commit_hash="c0ffee1"
    )
    assert op.git_sha == "c0ffee1"
