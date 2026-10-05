"""The server's half of the workflow YAML contract (#1618).

See ``scripts/workflow_yaml_reference.py``. The CLI's half is
``apps/syn-cli-node/tests/packages/workflow-yaml-reference.test.ts``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflow_yaml_reference import (  # noqa: E402
    FIXTURE,
    REPO_ROOT,
    Reference,
    build_reference,
    render,
)

from syn_domain.contexts.orchestration import (  # noqa: E402
    WorkflowDefinition,
    build_command_from_definition,
)

pytestmark = pytest.mark.unit

_COMMITTED = Reference.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
# Vendored `./skills/...` refs are resolved by the CLI's package loader before
# upload; this test inlines prompt files only, so these cannot be built here.
_NEEDS_PACKAGE_RESOLUTION = {
    "workflows/examples/starter-plugin/workflows/pr-review/workflow.yaml",
    "workflows/examples/starter-plugin/workflows/research/workflow.yaml",
    "workflows/validation/workflows/skills-injection/workflow.yaml",
}
_WITH_PHASES = sorted(
    path
    for path, ref in _COMMITTED.files.items()
    if ref.phases and path not in _NEEDS_PACKAGE_RESOLUTION
)


def test_fixture_is_what_pyyaml_reads_today() -> None:
    assert FIXTURE.read_text(encoding="utf-8") == render(build_reference()), (
        "a workflow YAML changed; run: uv run python scripts/workflow_yaml_reference.py --write"
    )


def test_implement_v3_has_ten_phases_through_its_merge_keys() -> None:
    phases = _COMMITTED.files["workflows/sdlc/implement-v3/workflow.yaml"].phases
    assert [p.id for p in phases] == [
        "premise", "implement", "verify",
        "fix", "reverify", "fix_2", "reverify_2", "fix_3", "reverify_3",
        "finalize_pr",
    ]  # fmt: skip


@pytest.mark.parametrize("rel_path", _WITH_PHASES)
def test_server_stores_every_phase_of_an_uploaded_definition(rel_path: str) -> None:
    """CLI upload -> /workflows/from-yaml -> stored command, minus the HTTP.

    `syn workflow install` uploads the parsed document as JSON with prompt
    files inlined; the endpoint runs `WorkflowDefinition.from_yaml` on those
    bytes and `build_command_from_definition` on the result. The CLI test pins
    that its upload carries exactly these phases.
    """
    path = REPO_ROOT / rel_path
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    WorkflowDefinition._resolve_prompt_files(document, path.parent)  # pyright: ignore[reportPrivateUsage]
    body = json.dumps(document)

    command = build_command_from_definition(WorkflowDefinition.from_yaml(body))

    assert [p.phase_id for p in command.phases] == [p.id for p in _COMMITTED.files[rel_path].phases]
