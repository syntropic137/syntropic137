"""Reading an orphan's identity and directory out of ``docker inspect`` (#1560)."""

from __future__ import annotations

import json

import pytest

from syn_adapters.workspace_backends.orphaned import parse_inspect

pytestmark = pytest.mark.unit


def test_labels_and_the_workspace_mount_source_are_read() -> None:
    raw = json.dumps(
        [
            {
                "Config": {"Labels": {"syn.execution_id": "exec-1"}},
                "Mounts": [
                    {"Destination": "/home/agent/.claude", "Source": "/elsewhere"},
                    {"Destination": "/workspace", "Source": "/root/.syntropic137/workspaces/ws-1"},
                ],
            }
        ]
    )
    inspected = parse_inspect(raw)
    assert inspected is not None
    assert inspected.labels == {"syn.execution_id": "exec-1"}
    assert inspected.workspace_source == "/root/.syntropic137/workspaces/ws-1"


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", json.dumps([{"Mounts": []}])])
def test_anything_unreadable_names_no_directory(raw: str) -> None:
    inspected = parse_inspect(raw)
    assert inspected is None or inspected.workspace_source is None
