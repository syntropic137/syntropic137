"""A phase's output is read whole beside a tree larger than the entry limit (#2185).

The toolchain image keeps rustup and the cargo registry in /workspace/.tools,
and a cloned superproject keeps its submodules in .git/modules. The provider
read used to walk all of /workspace and stop at `max_entries` before matching,
so every phase on such a workspace failed its collection after its work had
shipped, and its review and remediate phases never ran.

The real Docker provider's read, with syn137's own limits and glob, against a
live container holding more entries than the limit beside one deliverable.

Needs Docker; skipped when `docker info` does not answer within 10s.
"""

from __future__ import annotations

import subprocess
import uuid
from typing import TYPE_CHECKING

import pytest
from agentic_isolation.providers.docker_capabilities import read_files

from syn_adapters.workspace_backends.agentic.adapter_copy import collection_read_limits
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    _OUTPUT_GLOB,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

#: GNU find, as the workspace images have; busybox find has no -printf.
_IMAGE = "debian:bookworm-slim"


def _docker_answers() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=10,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
    pytest.mark.may_skip(reason="needs a Docker daemon", issue="#2185"),
    pytest.mark.skipif(not _docker_answers(), reason="docker info did not answer within 10s"),
]


@pytest.fixture
def container() -> Iterator[str]:
    """A live container: one deliverable, and a cache past the entry limit beside it."""
    entries = collection_read_limits().max_entries + 5_000
    name = f"syn-2185-{uuid.uuid4().hex[:12]}"
    seed = (
        "mkdir -p /workspace/artifacts/output /workspace/.tools/cargo && "
        "printf 'the work' > /workspace/artifacts/output/deliverable.md && "
        f"cd /workspace/.tools/cargo && seq 1 {entries} | xargs touch && "
        "exec sleep 600"
    )
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, _IMAGE, "sh", "-c", seed],
        check=True,
        capture_output=True,
        timeout=180,
    )
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                name,
                "sh",
                "-c",
                "until [ -s /workspace/artifacts/output/deliverable.md ] && "
                f'[ "$(ls /workspace/.tools/cargo | wc -l)" -ge {entries} ]; do sleep 1; done',
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False, timeout=60)


async def test_the_deliverable_is_read_whole_beside_a_tree_past_the_entry_limit(
    container: str,
) -> None:
    result = await read_files(container, [_OUTPUT_GLOB], "/workspace", collection_read_limits())

    assert result.complete, result.refused
    assert result.files == (("artifacts/output/deliverable.md", b"the work"),)
