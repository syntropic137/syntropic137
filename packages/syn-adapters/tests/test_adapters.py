"""Tests for adapters package."""

import pytest


@pytest.mark.unit
class TestAdaptersPackage:
    """Test adapters package initialization."""

    def test_import_adapters(self):
        """Test that adapters package can be imported."""
        import syn_adapters

        assert syn_adapters.__version__ == "0.1.0"

    def test_import_storage(self):
        """Test that storage module can be imported."""
        from syn_adapters import storage

        assert storage is not None
