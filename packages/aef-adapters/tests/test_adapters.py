"""Tests for adapters package."""


class TestAdaptersPackage:
    """Test adapters package initialization."""

    def test_import_adapters(self):
        """Test that adapters package can be imported."""
        import aef_adapters

        assert aef_adapters.__version__ == "0.1.0"

    def test_import_agents(self):
        """Test that agents module can be imported."""
        from aef_adapters import agents

        assert agents is not None

    def test_import_storage(self):
        """Test that storage module can be imported."""
        from aef_adapters import storage

        assert storage is not None
