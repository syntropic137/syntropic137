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
