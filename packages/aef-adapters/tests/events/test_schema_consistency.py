"""Tests to prevent schema drift between SQL migrations and Python code.

This ensures that:
1. Python EXPECTED_COLUMNS matches the SQL migration
2. Python CREATE TABLE statements match migrations (if they exist)
3. Docker init-db scripts include all required tables
"""

import re
from pathlib import Path

import pytest

from aef_adapters.events.models import EXPECTED_COLUMNS


class TestSchemaConsistency:
    """Verify schema definitions don't drift between sources."""

    @pytest.fixture
    def migrations_dir(self) -> Path:
        """Path to SQL migrations."""
        return Path(__file__).parent.parent.parent / "src/aef_adapters/projection_stores/migrations"

    @pytest.fixture
    def init_db_path(self) -> Path:
        """Path to Docker init-db script."""
        # Navigate up to repo root from:
        # packages/aef-adapters/tests/events/test_schema_consistency.py
        # -> packages/aef-adapters/tests/events
        # -> packages/aef-adapters/tests
        # -> packages/aef-adapters
        # -> packages
        # -> repo root
        repo_root = Path(__file__).parent.parent.parent.parent.parent
        return repo_root / "docker/init-db/01-create-databases.sql"

    def test_expected_columns_matches_migration(self, migrations_dir: Path) -> None:
        """EXPECTED_COLUMNS in Python must match 002_agent_events.sql."""
        migration_file = migrations_dir / "002_agent_events.sql"
        assert migration_file.exists(), f"Migration file not found: {migration_file}"

        sql_content = migration_file.read_text()

        # Parse CREATE TABLE statement
        # Looking for: column_name TYPE
        create_match = re.search(
            r"CREATE TABLE.*?agent_events\s*\((.*?)\);",
            sql_content,
            re.DOTALL | re.IGNORECASE,
        )
        assert create_match, "Could not find CREATE TABLE agent_events in migration"

        columns_sql = create_match.group(1)

        # Extract column definitions (name TYPE)
        # Pattern: word followed by type (TEXT, TIMESTAMPTZ, JSONB, etc.)
        column_pattern = re.compile(
            r"(\w+)\s+(TEXT|TIMESTAMPTZ|JSONB|INTEGER|BIGINT|BOOLEAN)", re.IGNORECASE
        )
        sql_columns = {
            match.group(1).lower(): match.group(2).lower()
            for match in column_pattern.finditer(columns_sql)
        }

        # Map Python types to SQL types for comparison
        type_mapping = {
            "timestamp with time zone": "timestamptz",
            "text": "text",
            "jsonb": "jsonb",
        }

        # Compare
        for col_name, expected_type in EXPECTED_COLUMNS.items():
            mapped_type = type_mapping.get(expected_type.lower(), expected_type.lower())
            sql_type = sql_columns.get(col_name.lower())

            assert sql_type is not None, (
                f"Column '{col_name}' in EXPECTED_COLUMNS not found in migration SQL"
            )
            assert sql_type == mapped_type, (
                f"Column '{col_name}' type mismatch: "
                f"Python expects '{expected_type}' but SQL has '{sql_type}'"
            )

    def test_session_conversations_in_init_db(self, init_db_path: Path) -> None:
        """Docker init-db must include session_conversations table."""
        assert init_db_path.exists(), f"Init-db script not found: {init_db_path}"

        sql_content = init_db_path.read_text()

        # Check for session_conversations table
        assert "session_conversations" in sql_content.lower(), (
            "session_conversations table missing from docker/init-db/01-create-databases.sql. "
            "This table is required for conversation log tracking (ADR-035)."
        )

    def test_migration_files_exist(self, migrations_dir: Path) -> None:
        """All expected migration files should exist."""
        expected_migrations = [
            "001_projection_tables.sql",
            "002_agent_events.sql",
            "003_session_conversations.sql",
        ]

        for migration in expected_migrations:
            migration_path = migrations_dir / migration
            assert migration_path.exists(), f"Migration file missing: {migration}"

    def test_no_uuid_columns_in_agent_events(self, migrations_dir: Path) -> None:
        """agent_events should use TEXT for IDs, not UUID (ADR-029 simplification)."""
        migration_file = migrations_dir / "002_agent_events.sql"
        sql_content = migration_file.read_text()

        # UUID columns are discouraged for simplicity
        uuid_matches = re.findall(r"(\w+)\s+UUID", sql_content, re.IGNORECASE)

        assert not uuid_matches, (
            f"Found UUID columns in agent_events migration: {uuid_matches}. "
            "Use TEXT for ID columns per ADR-029 simplified schema."
        )
