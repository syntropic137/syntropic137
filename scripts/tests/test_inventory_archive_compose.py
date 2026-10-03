"""Published deployments must keep the host-owned inventory archive (#1398)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_published_compose import _merge_volume_mounts, generate

pytestmark = pytest.mark.unit


def test_overlay_mounts_preserve_independent_base_volumes() -> None:
    merged = _merge_volume_mounts(
        ["archive:/app/archive", "old-work:/work"],
        ["new-work:/work:ro", "logs:/logs"],
    )
    assert merged == ["archive:/app/archive", "new-work:/work:ro", "logs:/logs"]


def test_published_api_archive_is_backed_by_a_declared_persistent_volume() -> None:
    published = generate()
    api = published["services"]["api"]
    target = api["environment"]["SYN_SESSION_INVENTORY_ARCHIVE_DIR"]
    assert f"session_inventory_data:{target}" in api["volumes"]
    assert "session_inventory_data" in published["volumes"]
    assert "./workspaces:/workspaces" in api["volumes"]
