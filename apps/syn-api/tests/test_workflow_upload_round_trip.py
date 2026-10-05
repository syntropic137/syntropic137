"""CLI parse -> API request -> stored definition, for every workflow (#1618).

``apps/syn-cli-node/tests/fixtures/workflow-upload-bodies.json`` is exactly
what ``syn workflow install`` uploads for each phase-bearing workflow YAML: the
CLI test builds it with the real package loader and fails when it is stale.
Here each body goes through the ``/workflows/from-yaml`` service into the
repository, and what was STORED is checked against what PyYAML reads from the
source file (``workflow-yaml-reference.json``). sdlc/implement-v3 went in as 4
phases instead of 10 through this path and nothing failed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from syn_api.types import Ok

if TYPE_CHECKING:
    from collections.abc import Iterator

os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from workflow_yaml_reference import FIXTURE, Reference  # noqa: E402

from syn_domain.contexts.orchestration import WorkflowDefinition  # noqa: E402

_UPLOADS_FILE = FIXTURE.parent / "workflow-upload-bodies.json"
_UPLOADS: dict[str, object] = json.loads(_UPLOADS_FILE.read_text(encoding="utf-8"))
_REFERENCE = Reference.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
# These declare vendored `./skills/...`. `syn workflow install` pins those refs
# through the skill-registration API (runSkillPreflight) before uploading, so the
# loader's body is not yet installable; the test below pins that the server
# refuses it rather than storing it. Their phases are checked CLI-side.
_NEEDS_SKILL_PREFLIGHT = {
    "workflows/examples/starter-plugin/workflows/pr-review/workflow.yaml",
    "workflows/examples/starter-plugin/workflows/research/workflow.yaml",
    "workflows/validation/workflows/skills-injection/workflow.yaml",
}


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


def test_every_phase_bearing_workflow_has_an_upload_body() -> None:
    with_phases = {rel for rel, ref in _REFERENCE.files.items() if ref.phases}
    assert set(_UPLOADS) == with_phases


@pytest.mark.parametrize("rel_path", sorted(_NEEDS_SKILL_PREFLIGHT))
async def test_vendored_skill_refs_are_refused_until_pinned(rel_path: str) -> None:
    from pydantic import ValidationError

    from syn_api.routes.workflows.commands import create_workflow_from_yaml

    with pytest.raises(ValidationError, match=r"skill reference './skills/"):
        await create_workflow_from_yaml(json.dumps(_UPLOADS[rel_path]))


@pytest.mark.parametrize("rel_path", sorted(set(_UPLOADS) - _NEEDS_SKILL_PREFLIGHT))
async def test_the_server_stores_every_phase_the_cli_uploads(rel_path: str) -> None:
    from syn_api._wiring import get_workflow_repo
    from syn_api.routes.workflows.commands import create_workflow_from_yaml

    result = await create_workflow_from_yaml(json.dumps(_UPLOADS[rel_path]))
    assert isinstance(result, Ok), result
    stored = await get_workflow_repo().get_by_id(result.value.workflow_id)
    assert stored is not None

    expected = _REFERENCE.files[rel_path].phases
    assert [(p.phase_id, p.order) for p in stored.phases] == [(p.id, p.order) for p in expected]

    source = _REPO_ROOT / rel_path
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    WorkflowDefinition._resolve_prompt_files(document, source.parent)  # pyright: ignore[reportPrivateUsage]
    assert [p.prompt_template for p in stored.phases] == [
        p.get("prompt_template") for p in document["phases"]
    ]


async def test_implement_v3_is_stored_with_all_ten_phases() -> None:
    from syn_api._wiring import get_workflow_repo
    from syn_api.routes.workflows.commands import create_workflow_from_yaml

    body = _UPLOADS["workflows/sdlc/implement-v3/workflow.yaml"]
    result = await create_workflow_from_yaml(json.dumps(body))
    assert isinstance(result, Ok), result
    stored = await get_workflow_repo().get_by_id(result.value.workflow_id)
    assert stored is not None
    assert [p.phase_id for p in stored.phases] == [
        "premise", "implement", "verify",
        "fix", "reverify", "fix_2", "reverify_2", "fix_3", "reverify_3",
        "finalize_pr",
    ]  # fmt: skip
