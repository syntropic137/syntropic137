"""Tests for the skills registration lookup endpoint."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.mark.unit
class TestSkillLookupResponse:
    def test_unregistered_reports_false_with_no_sha(self) -> None:
        from syn_api.types import SkillRegistrationLookupResponse

        response = SkillRegistrationLookupResponse(registered=False)

        assert response.registered is False
        assert response.resolved_sha is None

    def test_registered_carries_the_hash(self) -> None:
        """The sha is the cache key: a caller that has it can skip the upload."""
        from syn_api.types import SkillRegistrationLookupResponse

        response = SkillRegistrationLookupResponse(registered=True, resolved_sha="sha256-abc123")

        assert response.registered is True
        assert response.resolved_sha == "sha256-abc123"


@pytest.mark.unit
class TestSkillStorageStats:
    def test_reports_counts_and_bytes(self) -> None:
        """Eviction is not implemented (spec D6), so size must be visible."""
        from syn_api.types import SkillStorageStatsResponse

        stats = SkillStorageStatsResponse(object_count=42, total_bytes=1_048_576, skill_count=7)

        assert stats.object_count == 42
        assert stats.total_bytes == 1_048_576
        assert stats.skill_count == 7

    def test_empty_store_is_all_zeros_not_an_error(self) -> None:
        from syn_api.types import SkillStorageStatsResponse

        stats = SkillStorageStatsResponse()

        assert (stats.object_count, stats.total_bytes, stats.skill_count) == (0, 0, 0)
        assert stats.truncated is False
