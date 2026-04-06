"""Check for structural drift between committed OpenAPI spec and live FastAPI routes.

Compares endpoint paths + methods (not full JSON) so that minor Python version
differences in Pydantic schema serialization don't cause false positives.

Exits 0 if no structural drift, 1 if endpoints were added/removed/changed.

Usage:
    uv run python scripts/check_openapi_drift.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Set test environment before importing the app
os.environ["APP_ENVIRONMENT"] = "test"

SPEC_PATH = Path("apps/syn-docs/openapi.json")


def _extract_endpoints(spec: dict) -> set[str]:
    """Extract a set of 'METHOD /path' strings from an OpenAPI spec."""
    endpoints: set[str] = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                endpoints.add(f"{method.upper()} {path}")
    return endpoints


def main() -> None:
    if not SPEC_PATH.exists():
        print(f"ERROR: Committed OpenAPI spec not found at {SPEC_PATH}")
        print("Run: uv run python scripts/extract_openapi.py")
        sys.exit(1)

    # Load committed spec
    committed_spec = json.loads(SPEC_PATH.read_text())
    committed_endpoints = _extract_endpoints(committed_spec)

    # Generate fresh spec from current code
    from syn_api.main import create_app

    # Patch deferred annotations (same as extract_openapi.py)
    from datetime import datetime

    from pydantic import BaseModel

    from syn_api.routes import events

    ns = {"datetime": datetime}
    for attr_name in dir(events):
        attr = getattr(events, attr_name, None)
        if (
            isinstance(attr, type)
            and issubclass(attr, BaseModel)
            and attr.__module__ == events.__name__
        ):
            attr.model_rebuild(force=True, _types_namespace=ns)

    app = create_app()
    fresh_spec = app.openapi()
    fresh_endpoints = _extract_endpoints(fresh_spec)

    # Compare
    added = fresh_endpoints - committed_endpoints
    removed = committed_endpoints - fresh_endpoints

    if not added and not removed:
        print(f"No endpoint drift detected ({len(committed_endpoints)} endpoints).")
        sys.exit(0)

    print("ERROR: OpenAPI endpoint drift detected!")
    print()

    if added:
        print(f"  Endpoints in code but NOT in committed spec ({len(added)}):")
        for ep in sorted(added):
            print(f"    + {ep}")
        print()

    if removed:
        print(f"  Endpoints in committed spec but NOT in code ({len(removed)}):")
        for ep in sorted(removed):
            print(f"    - {ep}")
        print()

    print("Fix: run 'uv run python scripts/extract_openapi.py' and commit the result.")
    sys.exit(1)


if __name__ == "__main__":
    main()
