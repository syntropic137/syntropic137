"""Extract OpenAPI JSON spec from the AEF Dashboard FastAPI application.

Sets APP_ENVIRONMENT=test to skip credential validation during import.
Safe because the FastAPI lifespan only runs under uvicorn, not at import time.

Usage:
    uv run python scripts/extract_openapi.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Set test environment before importing the app to skip credential validation
os.environ["APP_ENVIRONMENT"] = "test"


def _patch_deferred_annotations() -> None:
    """Patch modules that use TYPE_CHECKING imports needed by Pydantic models.

    Some modules use `from __future__ import annotations` with TYPE_CHECKING
    imports for types used in Pydantic models. At schema-generation time,
    Pydantic can't resolve these deferred annotations. We pass a types namespace
    with the missing names when rebuilding.
    """
    from datetime import datetime

    from pydantic import BaseModel

    from syn_api.routes import events

    ns = {"datetime": datetime}

    # Rebuild only BaseModel subclasses defined in this module
    for attr_name in dir(events):
        attr = getattr(events, attr_name, None)
        if (
            isinstance(attr, type)
            and issubclass(attr, BaseModel)
            and attr.__module__ == events.__name__
        ):
            attr.model_rebuild(force=True, _types_namespace=ns)


def main() -> None:
    from syn_api.main import create_app

    _patch_deferred_annotations()

    app = create_app()
    spec = app.openapi()

    # Add top-level tags with descriptions (required for per-tag doc generation)
    tag_descriptions = {
        "workflows": "Manage workflow definitions and view run history",
        "execution": "Execute workflows and monitor active executions",
        "executions": "Query execution records and details",
        "control": "Pause, resume, cancel, and inject context into running executions",
        "sessions": "List and inspect agent sessions",
        "conversations": "Retrieve conversation logs and metadata",
        "artifacts": "Access artifacts produced by agent sessions",
        "costs": "Track token costs per session and execution",
        "metrics": "System-wide metrics and health data",
        "events": "Query session events, timelines, and tool usage",
        "observability": "Token metrics and tool timelines for sessions",
        "triggers": "Manage GitHub and webhook triggers for workflow automation",
        "webhooks": "Incoming webhook endpoints (GitHub events)",
        "websocket": "WebSocket health and real-time communication",
    }

    # Collect tags used by operations
    used_tags: set[str] = set()
    for path_item in spec.get("paths", {}).values():
        for method_data in path_item.values():
            if isinstance(method_data, dict):
                for tag in method_data.get("tags", []):
                    used_tags.add(tag)

    # Remap 'unknown' tag to 'metrics'
    for path_item in spec.get("paths", {}).values():
        for method_data in path_item.values():
            if isinstance(method_data, dict) and method_data.get("tags") == ["unknown"]:
                method_data["tags"] = ["metrics"]

    spec["tags"] = [
        {"name": tag, "description": tag_descriptions.get(tag, "")}
        for tag in sorted(used_tags - {"unknown"})
    ]

    output_path = Path("apps/syn-docs/openapi.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2) + "\n")

    endpoint_count = sum(len(methods) for methods in spec.get("paths", {}).values())
    print(f"Wrote OpenAPI spec to {output_path} ({endpoint_count} endpoints)")


if __name__ == "__main__":
    main()
