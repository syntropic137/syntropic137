"""Bundle context helpers for artifact storage.

Extracted from bundle_storage.py to reduce module cognitive complexity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.artifacts.bundle import ArtifactBundle


def create_context_summary(
    phase_id: str | None,
    workflow_id: str | None,
    task: str,
    system_prompt: str | None,
    artifacts: list[ArtifactBundle],
    context_files: list[tuple[Path, bytes]],
) -> str:
    """Create a JSON summary of the phase context."""
    summary = {
        "phase_id": phase_id,
        "workflow_id": workflow_id,
        "task": task,
        "system_prompt": system_prompt,
        "artifacts": [
            {
                "bundle_id": b.bundle_id,
                "phase_id": b.phase_id,
                "title": b.title,
                "file_count": b.file_count,
                "files": [str(f.path) for f in b.files],
            }
            for b in artifacts
        ],
        "context_files": [str(p) for p, _ in context_files],
    }
    return json.dumps(summary, indent=2)


def build_context_files(
    artifacts: list[ArtifactBundle],
    context_files: list[tuple[Path, bytes]],
    phase_id: str | None,
    workflow_id: str | None,
    task: str,
    system_prompt: str | None,
) -> list[tuple[Path, bytes]]:
    """Convert all artifacts and context to injectable files.

    Returns list of (relative_path, content) tuples ready for
    workspace injection.
    """
    files: list[tuple[Path, bytes]] = []

    # Add artifact files under .context/artifacts/{bundle_id}/
    for bundle in artifacts:
        bundle_dir = Path(".context") / "artifacts" / bundle.bundle_id

        for artifact_file in bundle.files:
            context_path = bundle_dir / artifact_file.path
            files.append((context_path, artifact_file.content))

        # Add bundle manifest
        manifest_path = bundle_dir / "manifest.json"
        manifest_content = bundle.to_json().encode("utf-8")
        files.append((manifest_path, manifest_content))

    # Add any additional context files
    for path, content in context_files:
        context_path = Path(".context") / path
        files.append((context_path, content))

    # Add phase context summary
    summary = create_context_summary(
        phase_id, workflow_id, task, system_prompt, artifacts, context_files
    )
    summary_path = Path(".context") / "context.json"
    files.append((summary_path, summary.encode("utf-8")))

    return files
