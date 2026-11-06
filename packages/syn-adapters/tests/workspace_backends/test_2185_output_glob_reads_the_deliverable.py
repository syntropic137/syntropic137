"""The phase output glob reads `artifacts/output/deliverable.md` (#2185).

`ArtifactCollector` asks for `artifacts/output/**/*`, and agentic-workspace
matches it with `fnmatch`, where `**/` needed at least one directory: the file
every phase writes, at the TOP of the output, never matched. The in-memory
workspace double reads `**/` as a globstar, and the #1913 transfer tests asked
for `artifacts/output/*`, so nothing here saw it.

Driven through production wiring and the production glob, over the E2B
provider and its in-memory account, whose listing stands in for the sandbox's.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.e2b import e2b_conformance as suite
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    _OUTPUT_GLOB,
)

from .test_1913_image_manifest_through_file_transfer import _e2b, _SeededSandboxes

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_the_deliverable_at_the_top_of_the_output_is_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _SeededSandboxes(
        {
            "/workspace/artifacts/output/deliverable.md": b"the work",
            "/workspace/artifacts/output/notes/n.md": b"n",
            "/workspace/artifacts/input/brief.md": b"not output",
        }
    )
    service = _e2b(monkeypatch, seeded)
    handle = await service._isolation.create(suite.isolation_config(service._config.image))

    got = await service._isolation.copy_from(handle, [_OUTPUT_GLOB])

    assert got == [
        ("artifacts/output/deliverable.md", b"the work"),
        ("artifacts/output/notes/n.md", b"n"),
    ]
