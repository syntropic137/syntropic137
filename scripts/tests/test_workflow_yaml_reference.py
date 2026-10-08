"""The server's half of the workflow YAML contract (#1618).

See ``scripts/workflow_yaml_reference.py``. The CLI's half is
``apps/syn-cli-node/tests/packages/workflow-yaml-reference.test.ts``, and the
stored round trip of what the CLI uploads is
``apps/syn-api/tests/test_workflow_upload_round_trip.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflow_yaml_reference import (
    FIXTURE,
    Reference,
    build_reference,
    render,
)

pytestmark = pytest.mark.unit

_COMMITTED = Reference.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_is_what_pyyaml_reads_today() -> None:
    assert FIXTURE.read_text(encoding="utf-8") == render(build_reference()), (
        "a workflow YAML changed; run: uv run python scripts/workflow_yaml_reference.py --write"
    )


def test_implement_v3_has_eight_phases_through_its_merge_keys() -> None:
    phases = _COMMITTED.files["workflows/sdlc/implement-v3/workflow.yaml"].phases
    assert [p.id for p in phases] == [
        "premise", "implement", "verify",
        "fix", "reverify", "fix_2", "reverify_2",
        "finalize_pr",
    ]  # fmt: skip


def test_reverify_pr_has_seven_phases_without_merge_keys() -> None:
    phases = _COMMITTED.files["workflows/sdlc/reverify-pr/workflow.yaml"].phases
    assert [p.id for p in phases] == [
        "prepare", "verify",
        "fix", "reverify", "fix_2", "reverify_2",
        "finalize_pr",
    ]  # fmt: skip
    assert [p.order for p in phases] == list(range(1, 8))
