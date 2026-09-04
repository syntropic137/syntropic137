"""A phase schema field must be applied or refused, never silently dropped.

ADR-069 D5. This is the rule that would have prevented #1039, where four
authored fields - `input_artifacts`, `allowed_tools`, `execution_type` and
`argument_hint` - were validated, persisted, projected, re-exported as YAML,
and then dropped before execution. `ExecutablePhase` has exactly ONE production
construction site, so a field not passed there is inert by construction, and
nothing failed: the phase ran, the dashboard rendered the value, and the
declaration meant nothing.

Type checking cannot catch this. Every dropped field had a default - `()`,
`[]`, `None`, `sequential` - so omitting it from the constructor is legal
Python and legal pyright. The only mechanical signal is the one below: for each
field the author can write, SOMETHING must either carry it into execution or
reject it at authoring time.

WHY A DECLARED TABLE AND NOT PURE INFERENCE. "Which execution symbol
corresponds to which YAML field" is not mechanically derivable - `id` becomes
`phase_id`, `output_artifacts` becomes `output_artifact_types`. So the mapping
is declared, and the drift guard is what stops the table going stale: a field
on the model and absent from the table fails, which is exactly the moment a new
field would otherwise go inert.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).resolve().parents[3]
_ORCHESTRATION = (
    _ROOT / "packages" / "syn-domain" / "src" / "syn_domain" / "contexts" / "orchestration"
)
_SCHEMA = _ORCHESTRATION / "_shared" / "workflow_definition.py"
#: The single production construction site for ExecutablePhase and the agent
#: config it carries. A field is "applied" only if it is PASSED here.
_HANDLER = _ORCHESTRATION / "slices" / "execute_workflow" / "ExecuteWorkflowHandler.py"

#: Fields carried into execution, mapped to (constructor, keyword).
#:
#: THE KEYWORD MUST BE PASSED AT THE CALL, not merely mentioned in the module.
#: An earlier version of this gate asserted the symbol appeared anywhere in the
#: execution path, and it PASSED with #1039 deliberately reintroduced -
#: `_wiring.py` reads `phase.agent_config.allowed_tools` whether or not the
#: handler ever sets it, so the mention proved nothing. A gate that cannot fail
#: on the bug it exists for certifies an open class as closed, so the check is
#: against the constructor keywords in the AST.
_APPLIED: dict[str, tuple[str, str]] = {
    "id": ("ExecutablePhase", "phase_id"),
    "name": ("ExecutablePhase", "name"),
    "order": ("ExecutablePhase", "order"),
    "description": ("ExecutablePhase", "description"),
    "prompt_template": ("ExecutablePhase", "prompt_template"),
    # `prompt_file` is resolved into `prompt_template` at load time, so it
    # rides the same keyword; it has no separate execution identity.
    "prompt_file": ("ExecutablePhase", "prompt_template"),
    "output_artifacts": ("ExecutablePhase", "output_artifact_types"),
    "timeout_seconds": ("ExecutablePhase", "timeout_seconds"),
    "claude_plugins": ("ExecutablePhase", "claude_plugins"),
    "skills": ("ExecutablePhase", "skills"),
    "allowed_tools": ("AgentConfiguration", "allowed_tools"),
    "model": ("AgentConfiguration", "model"),
    "agent": ("AgentConfiguration", "provider"),
}

#: Fields refused at authoring time, with WHY. Each must have a validator in
#: the schema module that raises. Refusal is a legitimate answer to D5: a
#: declaration the platform cannot honour should fail loudly when it is
#: written, not be accepted and ignored.
_REFUSED: dict[str, str] = {
    "max_tokens": "no agent CLI exposes a token cap (#964)",
    "execution_type": "only `sequential` is implemented; nothing branches on it (#1039)",
}

#: Fields that are DISPLAY metadata: they legitimately never reach execution,
#: and are applied by being rendered. Mapped to the UI source that renders them.
#:
#: This category exists because the first version of this gate did not have it,
#: and that omission nearly deleted a working field. `argument_hint` looks
#: exactly like an inert one - slash-command lineage, absent from the agent
#: command - and reasoning from lineage said "no consumer". It has one:
#: PhasePromptEditor renders it. "Applied" must not mean "reaches the agent
#: command", or this rule deletes every legitimately non-execution field.
_DISPLAYED: dict[str, str] = {
    "argument_hint": "apps/syn-dashboard-ui/src/pages/WorkflowDetail/PhasePromptEditor.tsx",
}

#: Fields VALIDATED as a cross-phase assertion rather than carried into
#: execution. Distinct from `_REFUSED`: the field is accepted, and a workflow
#: whose declaration does not resolve is rejected.
#: Each entry needs a BEHAVIOURAL fixture pair below, not just a rationale.
#: Without one this table is the gate's own loophole: a new inert field could
#: be parked here and the suite would prove nothing about it.
_VALIDATED: dict[str, str] = {
    "input_artifacts": (
        "declaration is keyed on artifact TYPES while injection is keyed on "
        "PHASE IDS, so it cannot be applied as a filter; checked instead that "
        "every declared type has a producer (#1039)"
    ),
}


def _phase_schema_fields() -> set[str]:
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        PhaseYamlDefinition,
    )

    return set(PhaseYamlDefinition.model_fields)


def _constructor_keywords(module: Path, constructor: str) -> set[str]:
    """Keyword names passed to every `constructor(...)` call in the module.

    `**kwargs` splats are deliberately NOT counted as covering a field: an
    unpacked mapping is unchecked, which is the same blindness that let these
    fields drop in the first place.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    passed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != constructor:
            continue
        passed.update(kw.arg for kw in node.keywords if kw.arg is not None)
    return passed


def _enforces(node: ast.FunctionDef) -> bool:
    """True if the validator body can reject a value.

    Two shapes count, and BOTH are needed. A `raise` inline is the obvious one.
    A call to a `require_*` guard is the other, and omitting it was a real false
    positive: `execution_type` delegates to `require_supported_execution_type`
    so the authoring check and the execution-boundary check cannot drift, and a
    raise-only detector called that unenforced when it is the stricter design.
    """
    for inner in ast.walk(node):
        if isinstance(inner, ast.Raise):
            return True
        if isinstance(inner, ast.Call):
            func = inner.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name.startswith("require_"):
                return True
    return False


def _validators_that_reject(module: Path) -> set[str]:
    """Field names whose validator can reject a value, found in the AST.

    Reads the `@field_validator("x")` decorator argument rather than grepping,
    so a field merely MENTIONED in a comment or a message string does not count
    as refused.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    refused: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not _enforces(node):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            target = decorator.func
            name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
            if name != "field_validator":
                continue
            for arg in decorator.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    refused.add(arg.value)
    return refused


class TestEveryAuthoredFieldHasAFate:
    def test_no_field_is_unclassified(self) -> None:
        """The drift guard. A new field must be classified before it can ship.

        This is the assertion that would have failed on the day each of the
        four inert fields was added, which is the whole point: the class
        recurs by omission, so the check has to be about omission.
        """
        classified = set(_APPLIED) | set(_REFUSED) | set(_VALIDATED) | set(_DISPLAYED)
        unclassified = _phase_schema_fields() - classified

        assert not unclassified, (
            f"Phase schema fields with no declared fate: {sorted(unclassified)}. "
            "ADR-069 D5: a field may exist only if some code path applies or "
            "refuses it. Add it to _APPLIED (and wire it), _REFUSED (and "
            "reject it), _VALIDATED (and check it), or _DISPLAYED (and render "
            "it) - do not leave it inert."
        )

    def test_the_table_does_not_name_fields_that_no_longer_exist(self) -> None:
        classified = set(_APPLIED) | set(_REFUSED) | set(_VALIDATED) | set(_DISPLAYED)
        stale = classified - _phase_schema_fields()

        assert not stale, f"Classified fields absent from the schema: {sorted(stale)}"

    def test_a_field_is_not_classified_twice(self) -> None:
        """Applied AND refused is incoherent, and would hide a real conflict."""
        pairs = [
            ("applied/refused", set(_APPLIED) & set(_REFUSED)),
            ("applied/validated", set(_APPLIED) & set(_VALIDATED)),
            ("applied/displayed", set(_APPLIED) & set(_DISPLAYED)),
            ("refused/validated", set(_REFUSED) & set(_VALIDATED)),
            ("refused/displayed", set(_REFUSED) & set(_DISPLAYED)),
            ("validated/displayed", set(_VALIDATED) & set(_DISPLAYED)),
        ]
        for label, overlap in pairs:
            assert not overlap, f"{label} overlap: {sorted(overlap)}"


class TestAppliedFieldsReachExecution:
    @pytest.mark.parametrize("field", sorted(_APPLIED))
    def test_the_carrying_keyword_is_passed_at_the_construction_site(self, field: str) -> None:
        """#1039 in one assertion, verified by reintroducing the bug.

        `allowed_tools` fails this when `_build_agent_config_from_phase` omits
        it from the `AgentConfiguration(...)` call - which is exactly the state
        the codebase was in, and exactly what nothing else detected.
        """
        constructor, keyword = _APPLIED[field]
        passed = _constructor_keywords(_HANDLER, constructor)

        assert keyword in passed, (
            f"Phase field '{field}' is classified as applied via "
            f"{constructor}(..., {keyword}=...), but no {constructor} call in "
            f"{_HANDLER.name} passes '{keyword}'. A field not passed at the "
            "single production construction site is inert BY CONSTRUCTION: it "
            "takes its default, no type checker objects, and the declaration "
            "silently means nothing (ADR-069 D5)."
        )


class TestRefusedFieldsAreActuallyRefused:
    @pytest.mark.parametrize("field", sorted(_REFUSED))
    def test_a_validator_raises_for_it(self, field: str) -> None:
        """Refusal must be enforced, not merely documented.

        Checked against the AST of the validator decorators, so a field named
        only in a comment or an error message does not pass.
        """
        assert field in _validators_that_reject(_SCHEMA), (
            f"Phase field '{field}' is classified as refused ({_REFUSED[field]}), "
            f"but no raising @field_validator in {_SCHEMA.name} names it. A "
            "refusal nobody enforces is the same as no rule."
        )

    @pytest.mark.parametrize("field", sorted(_REFUSED))
    def test_it_is_not_also_carried_into_execution(self, field: str) -> None:
        """A refused field must not ALSO be wired, which would be a live path
        for a value the schema says cannot arrive."""
        assert field not in _APPLIED


class TestDisplayedFieldsAreActuallyRendered:
    """A field excused from execution must EARN the excuse.

    Without this, `_DISPLAYED` is a place to hide any field someone does not
    want to wire, which is the loophole that makes the whole rule optional.
    """

    @pytest.mark.parametrize("field", sorted(_DISPLAYED))
    def test_the_named_ui_source_renders_it(self, field: str) -> None:
        source = _ROOT / _DISPLAYED[field]

        assert source.exists(), f"{source} does not exist; _DISPLAYED is stale"
        assert field in source.read_text(encoding="utf-8"), (
            f"Phase field '{field}' is classified as display metadata rendered "
            f"by {source.name}, but that file never names it. Either it is not "
            "displayed (so it is inert and must be wired or refused), or the "
            "renderer moved and this table is stale."
        )


#: One accepted and one rejected workflow per `_VALIDATED` field. The pair is
#: the contract: acceptance alone would pass with the validator deleted, and
#: rejection alone would pass with a validator that refuses everything.
_VALIDATION_FIXTURES: dict[str, tuple[dict[str, object], dict[str, object]]] = {
    "input_artifacts": (
        {
            "id": "wf-ok",
            "name": "ok",
            "type": "research",
            "phases": [
                {
                    "id": "producer",
                    "name": "p",
                    "order": 1,
                    "prompt_template": "x",
                    "output_artifacts": ["notes"],
                },
                {
                    "id": "consumer",
                    "name": "c",
                    "order": 2,
                    "prompt_template": "x",
                    "input_artifacts": ["notes"],
                },
            ],
        },
        {
            "id": "wf-bad",
            "name": "bad",
            "type": "research",
            "phases": [
                {
                    "id": "consumer",
                    "name": "c",
                    "order": 1,
                    "prompt_template": "x",
                    "input_artifacts": ["nothing_produces_this"],
                },
            ],
        },
    ),
}


class TestValidatedFieldsAreActuallyValidated:
    """`_VALIDATED` must not be a parking space for inert fields.

    A field classified here is neither carried into execution nor refused
    outright, so nothing else in this module constrains it. Without these two
    assertions per field, moving a new inert field into `_VALIDATED` would make
    the gate green while changing nothing - which is exactly the failure mode
    the gate exists to prevent.
    """

    def test_every_validated_field_has_a_fixture_pair(self) -> None:
        missing = set(_VALIDATED) - set(_VALIDATION_FIXTURES)

        assert not missing, (
            f"_VALIDATED fields with no behavioural fixture: {sorted(missing)}. "
            "Add an accepted and a rejected workflow, or the classification "
            "asserts nothing."
        )

    @pytest.mark.parametrize("field", sorted(_VALIDATION_FIXTURES))
    def test_the_valid_workflow_is_accepted(self, field: str) -> None:
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        good, _ = _VALIDATION_FIXTURES[field]

        assert WorkflowDefinition.model_validate(good) is not None

    @pytest.mark.parametrize("field", sorted(_VALIDATION_FIXTURES))
    def test_the_invalid_workflow_is_rejected(self, field: str) -> None:
        from pydantic import ValidationError

        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        _, bad = _VALIDATION_FIXTURES[field]

        with pytest.raises(ValidationError):
            WorkflowDefinition.model_validate(bad)
