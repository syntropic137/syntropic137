"""API contract test — OpenAPI spec vs TypeScript types.

Extracts field names from the auto-generated OpenAPI spec and compares
against the TypeScript interfaces in apps/syn-dashboard-ui/src/types/index.ts.

This catches drift between Python Pydantic schemas and manually-maintained TS types.
See issue #116 for the bugs that motivated this test.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

# Root of the repository
REPO_ROOT = Path(__file__).resolve().parents[3]
TS_TYPES_PATH = REPO_ROOT / "apps" / "syn-dashboard-ui" / "src" / "types" / "index.ts"


def _extract_openapi_schema_fields() -> dict[str, set[str]]:
    """Extract field names from each schema in the OpenAPI spec.

    Returns:
        Mapping of schema name → set of field names.
    """
    os.environ.setdefault("APP_ENVIRONMENT", "test")

    from syn_dashboard.main import create_app

    app = create_app()
    spec = app.openapi()

    schemas: dict[str, set[str]] = {}
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        props = schema.get("properties", {})
        if props:
            schemas[name] = set(props.keys())
    return schemas


def _extract_ts_interfaces() -> dict[str, set[str]]:
    """Parse TypeScript interface field names from types/index.ts.

    Returns:
        Mapping of interface name → set of field names.
    """
    if not TS_TYPES_PATH.exists():
        pytest.skip(f"TypeScript types file not found: {TS_TYPES_PATH}")

    content = TS_TYPES_PATH.read_text()
    interfaces: dict[str, set[str]] = {}

    # Match "export interface Name {" blocks
    iface_pattern = re.compile(r"export\s+interface\s+(\w+)\s*\{([^}]+)\}", re.DOTALL)
    for match in iface_pattern.finditer(content):
        name = match.group(1)
        body = match.group(2)
        fields: set[str] = set()
        for line in body.split("\n"):
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("/*"):
                continue
            # Match "field_name:" or "field_name?:"
            field_match = re.match(r"(\w+)\s*\??:", line)
            if field_match:
                fields.add(field_match.group(1))
        if fields:
            interfaces[name] = fields
    return interfaces


# Documented exceptions: fields that intentionally differ between Python and TS.
# Format: (openapi_schema_name, ts_interface_name, {fields_only_in_python}, {fields_only_in_ts})
KNOWN_EXCEPTIONS: list[tuple[str, str, set[str], set[str]]] = [
    # TS ArtifactResponse has extra UI-specific fields not in the OpenAPI schema
    (
        "ArtifactResponse",
        "ArtifactResponse",
        set(),
        {"is_primary_deliverable", "derived_from", "created_by", "metadata"},
    ),
    # TS SessionSummary has optional subagent fields from agentic_isolation v0.3.0
    (
        "SessionSummary",
        "SessionSummary",
        set(),
        {"subagent_count", "subagents", "tools_by_subagent", "num_turns", "duration_api_ms"},
    ),
    # TS SessionResponse has optional subagent fields; Python has workspace_path
    (
        "SessionResponse",
        "SessionResponse",
        {"workspace_path"},
        {"subagent_count", "subagents", "tools_by_subagent", "num_turns", "duration_api_ms"},
    ),
    # TS WorkflowSummary doesn't include optional fields from Python
    (
        "WorkflowSummary",
        "WorkflowSummary",
        {"classification", "description"},
        set(),
    ),
    # PhaseDefinition TS is minimal, Python has more config fields
    (
        "PhaseDefinition",
        "PhaseDefinition",
        {"prompt_template", "timeout_seconds", "allowed_tools"},
        set(),
    ),
    # OperationInfo: different field subsets for Python vs TS
    (
        "OperationInfo",
        "OperationInfo",
        {"input_preview", "output_preview", "observation_id"},
        {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "message_role",
            "message_content",
            "thinking_content",
            "operation_id",
        },
    ),
]


def _get_exception(py_name: str, ts_name: str) -> tuple[set[str], set[str]] | None:
    """Look up known exception for a schema pair."""
    for exc_py, exc_ts, only_py, only_ts in KNOWN_EXCEPTIONS:
        if exc_py == py_name and exc_ts == ts_name:
            return only_py, only_ts
    return None


# Mapping from OpenAPI schema name → TypeScript interface name
SCHEMA_TO_TS: dict[str, str] = {
    "ArtifactSummary": "ArtifactSummary",
    "ArtifactResponse": "ArtifactResponse",
    "SessionSummary": "SessionSummary",
    "SessionResponse": "SessionResponse",
    "WorkflowSummary": "WorkflowSummary",
    "WorkflowResponse": "WorkflowResponse",
    "WorkflowListResponse": "WorkflowListResponse",
}


@pytest.mark.unit
class TestAPIContract:
    """Verify OpenAPI schema fields match TypeScript interface fields."""

    @pytest.fixture(scope="class")
    def openapi_schemas(self) -> dict[str, set[str]]:
        return _extract_openapi_schema_fields()

    @pytest.fixture(scope="class")
    def ts_interfaces(self) -> dict[str, set[str]]:
        return _extract_ts_interfaces()

    def test_ts_types_file_exists(self) -> None:
        """TypeScript types file must exist."""
        assert TS_TYPES_PATH.exists(), f"Missing: {TS_TYPES_PATH}"

    def test_mapped_schemas_exist_in_openapi(self, openapi_schemas: dict[str, set[str]]) -> None:
        """All mapped schema names must appear in the OpenAPI spec."""
        for schema_name in SCHEMA_TO_TS:
            assert schema_name in openapi_schemas, (
                f"Schema '{schema_name}' not found in OpenAPI spec. "
                f"Available: {sorted(openapi_schemas.keys())}"
            )

    def test_mapped_interfaces_exist_in_ts(self, ts_interfaces: dict[str, set[str]]) -> None:
        """All mapped TS interface names must appear in types/index.ts."""
        for ts_name in SCHEMA_TO_TS.values():
            assert ts_name in ts_interfaces, (
                f"Interface '{ts_name}' not found in TypeScript types. "
                f"Available: {sorted(ts_interfaces.keys())}"
            )

    @pytest.mark.parametrize(
        "schema_name,ts_name",
        list(SCHEMA_TO_TS.items()),
        ids=list(SCHEMA_TO_TS.keys()),
    )
    def test_field_alignment(
        self,
        schema_name: str,
        ts_name: str,
        openapi_schemas: dict[str, set[str]],
        ts_interfaces: dict[str, set[str]],
    ) -> None:
        """Fields in OpenAPI schema must match TypeScript interface (with documented exceptions)."""
        if schema_name not in openapi_schemas:
            pytest.skip(f"Schema {schema_name} not in OpenAPI spec")
        if ts_name not in ts_interfaces:
            pytest.skip(f"Interface {ts_name} not in TS types")

        py_fields = openapi_schemas[schema_name]
        ts_fields = ts_interfaces[ts_name]

        only_in_py = py_fields - ts_fields
        only_in_ts = ts_fields - py_fields

        # Remove known exceptions
        exc = _get_exception(schema_name, ts_name)
        if exc:
            only_in_py -= exc[0]
            only_in_ts -= exc[1]

        assert not only_in_py, (
            f"{schema_name} has fields not in TS {ts_name}: {only_in_py}. "
            f"Add to TS types or document as exception."
        )
        assert not only_in_ts, (
            f"TS {ts_name} has fields not in {schema_name}: {only_in_ts}. "
            f"Add to Python schema or document as exception."
        )
