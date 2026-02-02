"""Tests for domain package."""

import pytest


@pytest.mark.unit
class TestDomainPackage:
    """Test domain package initialization."""

    def test_import_domain(self):
        """Test that domain package can be imported."""
        import aef_domain

        assert aef_domain.__version__ == "0.1.0"

    def test_import_contexts(self):
        """Test that contexts can be imported."""
        from aef_domain import contexts

        assert contexts is not None

    def test_import_orchestration_context(self):
        """Test that orchestration context can be imported."""
        from aef_domain.contexts import orchestration

        assert orchestration is not None

    def test_import_sessions_context(self):
        """Test that sessions context can be imported."""
        from aef_domain.contexts import sessions

        assert sessions is not None

    def test_import_agents_context(self):
        """Test that agents context can be imported."""
        from aef_domain.contexts import agents

        assert agents is not None

    def test_import_artifacts_context(self):
        """Test that artifacts context can be imported."""
        from aef_domain.contexts import artifacts

        assert artifacts is not None
