#!/usr/bin/env python3
"""Export JSON Schemas from Pydantic models for all plugin file formats.

This script is the bridge between Pydantic models (source of truth) and the
JSON Schema files consumed by editors, the Node.js CLI (Zod), CI validation,
and plugin authors.

Generated schemas are written to schemas/plugin/*.schema.json.

Usage:
    uv run python scripts/export_plugin_schemas.py

CI staleness check:
    uv run python scripts/export_plugin_schemas.py --check
    (exits non-zero if schemas are out of date)

See ADR-053 for the full schema generation strategy.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Ensure the repo root is importable so we can reach all packages.
# The uv workspace should handle this, but be explicit for clarity.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas" / "plugin"

# Add repo root to sys.path so schemas/ is importable.
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Import the Pydantic models that are the source of truth.
#
# Each model owns one schema file. If you add a new plugin file format,
# add its Pydantic model here and register it in SCHEMA_REGISTRY below.
#
# These imports must come after sys.path.insert above, hence the E402 noqa.
# ---------------------------------------------------------------------------

from schemas.plugin.trigger_file_schema import TriggerFileSchema  # noqa: E402

from syn_cli.commands._marketplace_models import MarketplaceIndex  # noqa: E402
from syn_cli.commands._package_models import PluginManifest  # noqa: E402
from syn_domain.contexts.orchestration._shared.workflow_definition import (  # noqa: E402
    PhaseFrontmatterSchema,
    WorkflowDefinition,
)

# ---------------------------------------------------------------------------
# Schema registry — maps output filename to Pydantic model.
#
# To add a new schema:
# 1. Create or identify the Pydantic model (source of truth)
# 2. Import it above
# 3. Add an entry here
# 4. Run this script to generate the schema
# 5. Commit the generated .schema.json file
# ---------------------------------------------------------------------------

SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "workflow.schema.json": WorkflowDefinition,
    "plugin-manifest.schema.json": PluginManifest,
    "marketplace.schema.json": MarketplaceIndex,
    "triggers.schema.json": TriggerFileSchema,
    "phase-frontmatter.schema.json": PhaseFrontmatterSchema,
}


def _read_platform_version() -> str:
    """Read the platform version from pyproject.toml."""
    pyproject = REPO_ROOT / "pyproject.toml"
    match = re.search(r'^version\s*=\s*"(.+?)"', pyproject.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read version from pyproject.toml")
    return match.group(1)


PLATFORM_VERSION = _read_platform_version()
SCHEMA_BASE_URL = "https://syntropic137.dev/schemas/plugin"


def generate_schema(name: str, model: type[BaseModel]) -> str:
    """Generate a formatted JSON Schema string from a Pydantic model."""
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"{SCHEMA_BASE_URL}/v{PLATFORM_VERSION}/{name}"
    # Move $schema and $id to the top for readability
    ordered = {"$schema": schema.pop("$schema"), "$id": schema.pop("$id"), **schema}
    return json.dumps(ordered, indent=2) + "\n"


def export_all() -> dict[str, str]:
    """Generate all schemas and return filename → content mapping."""
    return {name: generate_schema(name, model) for name, model in SCHEMA_REGISTRY.items()}


def write_schemas(schemas: dict[str, str]) -> None:
    """Write schemas to disk."""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in schemas.items():
        path = SCHEMA_DIR / name
        path.write_text(content, encoding="utf-8")
        print(f"  Wrote {path.relative_to(REPO_ROOT)}")


def check_staleness(schemas: dict[str, str]) -> bool:
    """Check if committed schemas match generated output. Returns True if stale."""
    stale = False
    for name, expected in schemas.items():
        path = SCHEMA_DIR / name
        if not path.exists():
            print(f"  MISSING: {path.relative_to(REPO_ROOT)}")
            stale = True
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            print(f"  STALE: {path.relative_to(REPO_ROOT)}")
            stale = True

    # Detect orphaned schema files not in the registry.
    if SCHEMA_DIR.exists():
        for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
            if path.name not in schemas:
                print(f"  ORPHAN: {path.relative_to(REPO_ROOT)} (not in SCHEMA_REGISTRY)")
                stale = True

    return stale


def main() -> None:
    check_mode = "--check" in sys.argv

    print("Generating plugin schemas from Pydantic models...")
    print(f"  Source of truth: {len(SCHEMA_REGISTRY)} models")
    print(f"  Output: {SCHEMA_DIR.relative_to(REPO_ROOT)}/")
    print()

    schemas = export_all()

    if check_mode:
        print("Checking for staleness...")
        if check_staleness(schemas):
            print()
            print("Schemas are out of date! Run:")
            print("  uv run python scripts/export_plugin_schemas.py")
            sys.exit(1)
        else:
            print("  All schemas up to date.")
    else:
        write_schemas(schemas)
        print()
        print(f"Done. {len(schemas)} schemas exported.")


if __name__ == "__main__":
    main()
