"""Tests for domain package."""

import pytest


@pytest.mark.unit
class TestDomainPackage:
    """Test domain package initialization."""

    def test_import_domain(self):
        """Test that domain package can be imported."""
        import syn_domain

        assert syn_domain is not None
        # No ``__version__``: the release lives in pyproject.toml and nowhere
        # else. Asserting its absence, not just dropping the old assertion,
        # because a literal reintroduced here is guaranteed to be wrong -
        # `just bump-version` does not write dunders (#1380).
        assert not hasattr(syn_domain, "__version__")

    def test_import_contexts(self):
        """Test that contexts can be imported."""
        from syn_domain import contexts

        assert contexts is not None

    def test_import_orchestration_context(self):
        """Test that orchestration context can be imported."""
        from syn_domain.contexts import orchestration

        assert orchestration is not None

    def test_import_agent_sessions_context(self):
        """Test that agent_sessions context can be imported."""
        from syn_domain.contexts import agent_sessions

        assert agent_sessions is not None

    def test_import_artifacts_context(self):
        """Test that artifacts context can be imported."""
        from syn_domain.contexts import artifacts

        assert artifacts is not None
