"""Fitness: GitHubEventsCursor enforces typed HWM persistence.

The principal #694 fix relies on every saved cursor carrying a
last_event_id high-water mark. Making last_event_id a REQUIRED
dataclass field (no default) means: bypassing the fix requires
constructing the dataclass without the field, which is a type error.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import dataclasses

import pytest


@pytest.mark.architecture
class TestGitHubCursorTyped:
    def test_has_required_last_event_id_field(self) -> None:
        from syn_domain.contexts.github.services.github_events_cursor import (
            GitHubEventsCursor,
        )

        fields = {f.name: f for f in dataclasses.fields(GitHubEventsCursor)}
        assert "last_event_id" in fields, "Cursor must have last_event_id field"
        assert fields["last_event_id"].default is dataclasses.MISSING, (
            "last_event_id must be required (no default), making the #694 fix "
            "non-bypassable: any caller persisting a cursor MUST supply HWM."
        )
        assert "etag" in fields
        assert fields["etag"].default is dataclasses.MISSING

    def test_round_trip_through_cursor_data(self) -> None:
        from syn_domain.contexts.github.services.github_events_cursor import (
            GitHubEventsCursor,
        )

        original = GitHubEventsCursor(etag='W/"abc"', last_event_id="999")
        round_tripped = GitHubEventsCursor.from_cursor_data(original.to_cursor_data())
        assert round_tripped == original

    def test_from_cursor_data_handles_none(self) -> None:
        from syn_domain.contexts.github.services.github_events_cursor import (
            GitHubEventsCursor,
        )

        empty = GitHubEventsCursor.from_cursor_data(None)
        assert empty.etag == ""
        assert empty.last_event_id == ""

    def test_is_newer_than_uses_int_comparison(self) -> None:
        """Lexicographic comparison fails for "10" > "9"; must compare as ints."""
        from syn_domain.contexts.github.services.github_events_cursor import (
            GitHubEventsCursor,
        )

        cursor = GitHubEventsCursor(etag="", last_event_id="9")
        assert cursor.is_newer_than("10") is True

    def test_is_newer_than_rejects_malformed_event_id(self) -> None:
        """Malformed event ID -> reject (safer than re-process)."""
        from syn_domain.contexts.github.services.github_events_cursor import (
            GitHubEventsCursor,
        )

        cursor = GitHubEventsCursor(etag="", last_event_id="42")
        assert cursor.is_newer_than("not-a-number") is False
