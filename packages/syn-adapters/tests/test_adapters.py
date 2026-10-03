"""Tests for adapters package."""

import pytest


@pytest.mark.unit
class TestAdaptersPackage:
    """Test adapters package initialization."""

    def test_import_adapters(self):
        """Test that adapters package can be imported."""
        import syn_adapters

        assert syn_adapters is not None
        # No ``__version__``: the release lives in pyproject.toml and nowhere
        # else. Asserting its absence, not just dropping the old assertion,
        # because a literal reintroduced here is guaranteed to be wrong -
        # `just bump-version` does not write dunders (#1380).
        assert not hasattr(syn_adapters, "__version__")

    def test_import_storage(self):
        """Test that storage module can be imported."""
        from syn_adapters import storage

        assert storage is not None
