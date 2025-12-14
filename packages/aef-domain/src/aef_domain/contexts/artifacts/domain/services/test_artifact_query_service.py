"""Tests for ArtifactQueryService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from aef_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)
from aef_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
    ArtifactQueryServiceProtocol,
)


class TestArtifactQueryServiceProtocol:
    """Tests for the protocol definition."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """Verify the protocol is runtime checkable."""
        service = ArtifactQueryService(MagicMock())
        assert isinstance(service, ArtifactQueryServiceProtocol)


class TestArtifactQueryService:
    """Tests for ArtifactQueryService implementation."""

    @pytest.fixture
    def mock_projection(self) -> MagicMock:
        """Create a mock projection."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_projection: MagicMock) -> ArtifactQueryService:
        """Create a service with mock projection."""
        return ArtifactQueryService(mock_projection)

    @pytest.mark.asyncio
    async def test_get_by_execution_delegates_to_projection(
        self,
        service: ArtifactQueryService,
        mock_projection: MagicMock,
    ) -> None:
        """Test that get_by_execution delegates to projection."""
        expected_artifacts = [
            ArtifactSummary(
                id="art-1",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="research",
                artifact_type="markdown",
                name="Research Output",
                created_at=None,
            )
        ]
        mock_projection.get_by_execution = AsyncMock(return_value=expected_artifacts)

        result = await service.get_by_execution("exec-1")

        mock_projection.get_by_execution.assert_called_once_with("exec-1")
        assert result == expected_artifacts

    @pytest.mark.asyncio
    async def test_get_for_phase_injection_returns_phase_content(
        self,
        service: ArtifactQueryService,
        mock_projection: MagicMock,
    ) -> None:
        """Test that get_for_phase_injection returns phase content dict."""
        artifacts = [
            ArtifactSummary(
                id="art-1",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="research",
                artifact_type="markdown",
                name="Research Output",
                created_at=None,
                content="Research content here",
            ),
            ArtifactSummary(
                id="art-2",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="planning",
                artifact_type="markdown",
                name="Planning Output",
                created_at=None,
                content="Planning content here",
            ),
        ]
        mock_projection.get_by_execution = AsyncMock(return_value=artifacts)

        result = await service.get_for_phase_injection(
            execution_id="exec-1",
            completed_phase_ids=["research", "planning"],
        )

        assert result == {
            "research": "Research content here",
            "planning": "Planning content here",
        }

    @pytest.mark.asyncio
    async def test_get_for_phase_injection_filters_by_completed_phases(
        self,
        service: ArtifactQueryService,
        mock_projection: MagicMock,
    ) -> None:
        """Test that only completed phases are included."""
        artifacts = [
            ArtifactSummary(
                id="art-1",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="research",
                artifact_type="markdown",
                name="Research Output",
                created_at=None,
                content="Research content",
            ),
            ArtifactSummary(
                id="art-2",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="planning",
                artifact_type="markdown",
                name="Planning Output",
                created_at=None,
                content="Planning content",
            ),
        ]
        mock_projection.get_by_execution = AsyncMock(return_value=artifacts)

        # Only request research, not planning
        result = await service.get_for_phase_injection(
            execution_id="exec-1",
            completed_phase_ids=["research"],
        )

        assert result == {"research": "Research content"}
        assert "planning" not in result

    @pytest.mark.asyncio
    async def test_get_for_phase_injection_skips_empty_content(
        self,
        service: ArtifactQueryService,
        mock_projection: MagicMock,
    ) -> None:
        """Test that artifacts without content are skipped."""
        artifacts = [
            ArtifactSummary(
                id="art-1",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="research",
                artifact_type="markdown",
                name="Research Output",
                created_at=None,
                content=None,  # No content
            ),
        ]
        mock_projection.get_by_execution = AsyncMock(return_value=artifacts)

        result = await service.get_for_phase_injection(
            execution_id="exec-1",
            completed_phase_ids=["research"],
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_for_phase_injection_uses_first_artifact_per_phase(
        self,
        service: ArtifactQueryService,
        mock_projection: MagicMock,
    ) -> None:
        """Test that only the first artifact per phase is used."""
        artifacts = [
            ArtifactSummary(
                id="art-1",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="research",
                artifact_type="markdown",
                name="First Artifact",
                created_at=None,
                content="First content",
            ),
            ArtifactSummary(
                id="art-2",
                workflow_id="wf-1",
                execution_id="exec-1",
                session_id=None,
                phase_id="research",  # Same phase!
                artifact_type="markdown",
                name="Second Artifact",
                created_at=None,
                content="Second content",
            ),
        ]
        mock_projection.get_by_execution = AsyncMock(return_value=artifacts)

        result = await service.get_for_phase_injection(
            execution_id="exec-1",
            completed_phase_ids=["research"],
        )

        # Should only contain the first artifact's content
        assert result == {"research": "First content"}

    @pytest.mark.asyncio
    async def test_get_for_phase_injection_empty_phases(
        self,
        service: ArtifactQueryService,
        mock_projection: MagicMock,
    ) -> None:
        """Test with empty completed phases list."""
        mock_projection.get_by_execution = AsyncMock(return_value=[])

        result = await service.get_for_phase_injection(
            execution_id="exec-1",
            completed_phase_ids=[],
        )

        assert result == {}
