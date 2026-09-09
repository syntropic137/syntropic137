"""Validate every workflow YAML in the repo against WorkflowDefinition.

The schema pipeline was already 90% built: WorkflowDefinition is the source of
truth, `export_plugin_schemas.py` generates workflow.schema.json from it, and
`check-plugin-schemas` fails if the two drift. What nobody did was run the
repo's own workflow FILES through it.

So a workflow could declare a shape the platform rejects and reach the
dashboard, where the field renders and can never be submitted (#942). The
schema was right the whole time; nothing pointed it at the workflows.

It also checks something the API does NOT: that a phase's prompt and its tool
grant agree. That is a coherence property of the pair, not a validity property
of either half, so no schema can express it and the create endpoint accepts a
workflow that has it wrong. See `grant_violations`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PhaseYamlDefinition,
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration._shared.yaml_to_command import build_command_from_definition

if TYPE_CHECKING:
    from collections.abc import Callable

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


#: A fenced shell block in a prompt is the phase being told to run shell.
#:
#: Deliberately the fence and not a vocabulary of commands. A list of
#: interesting binaries is a special case per binary, always one short, and
#: whichever one it is missing is the one the next prompt uses. A fence says
#: "run this" in the prompt's own syntax and needs no such list.
_SHELL_FENCE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+\.)?[ \t]*```[ \t]*(?:bash|sh|shell|zsh|console)\b", re.M
)


def _told_to_run_shell(phase: PhaseYamlDefinition) -> str | None:
    # from_file has already inlined prompt_file into prompt_template, so this
    # is the prompt the agent is handed however it was written.
    prompt = phase.prompt_template or ""
    match = _SHELL_FENCE.search(prompt)
    if match is None:
        return None
    return f"prompt line {prompt.count('\n', 0, match.start()) + 1}"


def _required_to_produce_an_artifact(phase: PhaseYamlDefinition) -> str | None:
    # `output_artifacts` and not a phrase in the prompt. Every phase states its
    # deliverable twice - once in prose and once in this field - and only the
    # field is structured. Reading the prose instead would mean matching "write
    # to artifacts/output", which the phases that only READ that directory also
    # say, in the boilerplate that tells them where their input came from.
    if not phase.output_artifacts:
        return None
    return f"it declares output_artifacts {phase.output_artifacts}"


@dataclass(frozen=True)
class _Demand:
    """Something a phase is REQUIRED to be able to do, and what would let it.

    Each demand knows how to find itself in a phase, so a new capability is one
    entry in `_DEMANDS` rather than another branch in the loop below. Where the
    requirement is stated differs - the shell one is in the prompt, the artifact
    one is in the phase's own declarations - and that difference is this type's
    whole job to absorb: the caller asks "is this phase able to do what it must"
    and never learns which half of the file the answer came from.
    """

    #: Completes "phase X must ...", so phrase it as a verb.
    must: str
    #: Holding ANY of these satisfies the demand. More than one because there
    #: is usually more than one honest way: a phase with Bash can create a file
    #: with a heredoc and needs no Write to do it.
    satisfied_by: frozenset[str]
    #: Where the requirement is stated, or None when this phase has no such
    #: requirement.
    locate: Callable[[PhaseYamlDefinition], str | None]


_DEMANDS: tuple[_Demand, ...] = (
    _Demand(
        must="run shell",
        satisfied_by=frozenset({"Bash"}),
        locate=_told_to_run_shell,
    ),
    _Demand(
        must="create a file",
        satisfied_by=frozenset({"Bash", "Write"}),
        locate=_required_to_produce_an_artifact,
    ),
)


def grant_violations(path: Path) -> list[str]:
    """Phases in this file that must do something their tool grant forbids.

    THE INVARIANT: a phase's instructions and its tool grant must agree. Every
    phase told to do something must be able to do it; every phase that must not
    do something must not be told to.

    WHY A GATE AND NOT A REVIEW. #1110 added a `gh pr comment` step to the
    pr-review `report` prompt. `report` grants Read, Grep, Glob, Write - no
    Bash. The install succeeded, the deployed prompt carried the step, and
    three reviews (#1113, #1115, #1117) each wrote "this needs a tool this
    phase does not have" while their verdicts stayed in object storage (#1122).
    Nothing failed. Both halves were individually valid and only the pair was
    wrong, which is exactly the shape a human reviewer reads past: the prompt
    is in one file and the grant is in another.

    WHY IT CHECKS MORE THAN THE PROMPT. The first version of this gate knew
    only the shell fence, and #1122's own fix then missed three phases of
    `research-experiment-plan` that declare a markdown output while granting
    [Read, Grep, Glob] - no Write, no Bash, so nothing they produced could
    reach `artifacts/output/` and the phase after each of them reads an empty
    directory. Same defect, stated in the declaration rather than in a fence.
    A gate that knows one spelling of a defect certifies the others.

    An empty allowlist is not a restriction - `_build_agent_command` omits
    `--tools` entirely - so those phases hold every tool and cannot violate
    this. Codex phases are in that set by construction; the validator already
    refuses a tool list on them.
    """
    definition = WorkflowDefinition.from_file(path)
    violations: list[str] = []
    for phase in definition.phases:
        # A bare name is the only spelling that exists: `allowed_tools` is
        # validated against a fixed vocabulary, so `Bash(gh:*)` is refused at
        # load and never reaches here (#1207).
        granted = set(phase.allowed_tools)
        if not granted:
            continue
        for demand in _DEMANDS:
            if granted & demand.satisfied_by:
                continue
            where = demand.locate(phase)
            if where is None:
                continue
            missing = ", ".join(sorted(demand.satisfied_by))
            violations.append(
                f"phase '{phase.id}' must {demand.must} ({where}) but its "
                f"allowed_tools are [{', '.join(phase.allowed_tools)}] - none of "
                f"[{missing}]. Either grant one or drop the requirement; do not "
                f"ship the pair."
            )
    return violations


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
            continue
        # Only once the file is known to load: `grant_violations` re-reads it
        # through `from_file`, which is what raised above.
        failures.extend((path, why) for why in grant_violations(path))

    for path, why in failures:
        print(f"  FAIL {path.relative_to(_ROOT)}\n       {why}")

    if failures:
        print(f"\n{len(failures)} of {checked} workflow definition(s) are invalid.")
        return 1

    print(f"✅ {checked} workflow definition(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
