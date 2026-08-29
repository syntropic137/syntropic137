"""Validate every workflow YAML in the repo against WorkflowDefinition.

The schema pipeline was already 90% built: WorkflowDefinition is the source of
truth, `export_plugin_schemas.py` generates workflow.schema.json from it, and
`check-plugin-schemas` fails if the two drift. What nobody did was run the
repo's own workflow FILES through it.

So a workflow could declare a shape the platform rejects and reach the
dashboard, where the field renders and can never be submitted (#942). The
schema was right the whole time; nothing pointed it at the workflows.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import build_command_from_definition

_ROOT = Path(__file__).resolve().parent.parent
_ROOTS = ("workflows",)


def _is_package_member(path: Path) -> bool:
    """True when this file belongs to a workflow PACKAGE rather than standing alone.

    A package carries a plugin manifest at its root; its workflow files may use
    package-relative skill references that only resolve in that context.
    """
    for parent in path.parents:
        if parent == _ROOT:
            break
        if any(
            (parent / n).exists()
            for n in ("syntropic137-plugin.json", "syntropic137.yaml", "marketplace.json")
        ):
            return True
    return False


def _workflow_files() -> list[Path]:
    found: list[Path] = []
    for root in _ROOTS:
        base = _ROOT / root
        if base.exists():
            found.extend(sorted(p for p in base.rglob("*.yaml") if p.is_file()))
    return found


def validate_file(path: Path) -> str | None:
    """Validate ONE workflow file to the depth the create endpoint uses.

    Returns the failure reason, or None when the file is acceptable.

    Extracted so tests can drive the real thing. The first version of the test
    file reimplemented this logic, so reverting the gate to a shallow
    `model_validate` left every test green - a test suite measuring its own
    copy of the code rather than the code.
    """
    try:
        # from_file, NOT model_validate(raw): the parse model accepts a
        # `prompt_file` that does not exist, and the API's create endpoint
        # then rejects it at conversion with HTTP 400. A gate that stops at
        # the parse model passes definitions the platform refuses, which is
        # the exact class it exists to catch.
        definition = WorkflowDefinition.from_file(path)
        # Then the SAME conversion the create endpoint runs. Loading is not
        # validation: an unresolved prompt_file is rejected here, not above.
        build_command_from_definition(definition)
    # OSError too: `from_file` raises FileNotFoundError for an unresolved
    # prompt_file, and letting that escape crashes the gate with a traceback
    # instead of naming the file and the reason.
    except (ValidationError, ValueError, OSError) as exc:
        return str(exc)
    return None


def main() -> int:
    files = _workflow_files()
    if not files:
        print("No workflow YAML found - nothing to validate.")
        return 0

    failures: list[tuple[Path, str]] = []
    checked = 0
    for path in files:
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            failures.append((path, f"unparseable YAML: {exc}"))
            continue
        if not isinstance(raw, dict) or "phases" not in raw:
            # Not a workflow definition (marketplace manifests, fragments).
            continue
        if _is_package_member(path):
            # Package-relative skill refs ('./skills/x') resolve against the
            # plugin root, which only exists when the package is validated as a
            # whole. Validating the file in isolation reports a failure the
            # supported path does not have - `syn workflow validate <dir>`
            # accepts these. Skipped here and covered by the package check.
            continue
        checked += 1
        reason = validate_file(path)
        if reason is not None:
            failures.append((path, reason))

    for path, why in failures:
        print(f"  FAIL {path.relative_to(_ROOT)}\n       {why}")

    if failures:
        print(f"\n{len(failures)} of {checked} workflow definition(s) are invalid.")
        return 1

    print(f"✅ {checked} workflow definition(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
