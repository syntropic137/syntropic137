"""Translate untyped workflow-create payloads into domain value objects.

The create route accepts phases and input declarations as plain mappings; this
module owns the mapping from those payloads onto ``PhaseDefinition``,
``InputDeclaration``, ``WorkflowType`` and ``WorkflowClassification``,
including the sandbox runnability check every phase must pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syn_shared.agents import (
    DEFAULT_PHASE_SANDBOX,
    require_enforceable_cost_limit,
    require_runnable_sandbox,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        FallbackAgent,
        InputDeclaration,
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )


def _resolve_workflow_type(workflow_type: str) -> WorkflowType:
    from syn_domain.contexts.orchestration import WorkflowType

    type_map: dict[str, WorkflowType] = {
        "research": WorkflowType.RESEARCH,
        "planning": WorkflowType.PLANNING,
        "implementation": WorkflowType.IMPLEMENTATION,
        "review": WorkflowType.REVIEW,
        "deployment": WorkflowType.DEPLOYMENT,
        "custom": WorkflowType.CUSTOM,
    }
    return type_map.get(workflow_type.lower(), WorkflowType.CUSTOM)


def _resolve_classification(classification: str) -> WorkflowClassification:
    from syn_domain.contexts.orchestration import WorkflowClassification

    classification_map: dict[str, WorkflowClassification] = {
        "simple": WorkflowClassification.SIMPLE,
        "standard": WorkflowClassification.STANDARD,
        "complex": WorkflowClassification.COMPLEX,
        "epic": WorkflowClassification.EPIC,
    }
    return classification_map.get(classification.lower(), WorkflowClassification.STANDARD)


def _as_bool(value: object, field: str) -> bool:
    """Only a real bool. Anything else is the caller's error, so say so.

    `bool("false")` is True, so coercion turned `allow_delegation: "false"`
    into delegation ENABLED -- asking for the feature off and getting it on.
    The first fix silently defaulted a non-bool to False instead, which is
    fail-closed but still wrong in the other direction: `1` and `"true"`
    became False, so a caller asking for it ON silently got it OFF, with a
    201. Trading one silent corruption for another is not a fix.

    A JSON boolean literal arrives as a real bool; only a QUOTED value
    arrives as a string, and that is a malformed request, not an opinion.
    """
    if isinstance(value, bool):
        return value
    msg = f"phase field {field!r} must be a boolean, got {type(value).__name__}: {value!r}"
    raise ValueError(msg)


def _expand_skills(entries: Iterable[object] | None) -> tuple[SkillRef, ...]:
    """Expand each entry the way the YAML path does.

    Passing raw entries straight to `SkillRef` looked equivalent and is not:
    the verbose form `{"source": ..., "names": ["alpha", "beta"]}` declares
    TWO skills, and direct validation produced ONE named after the repo. So a
    caller asking for `alpha` and `beta` silently got a single skill called
    `b` -- a wrong identity rather than a missing one, which resolves and
    injects the wrong instructions.

    That is worse than the bug this PR set out to fix. `main` dropped skills
    entirely; absent is recoverable, wrong is not.
    """
    from syn_domain.contexts.orchestration._shared.skill_ref import expand_skill_entry

    if not entries:
        return ()
    expanded: list[SkillRef] = []
    for entry in entries:
        expanded.extend(expand_skill_entry(entry))
    return tuple(expanded)


def _agent_field(phase: Mapping[str, Any], name: str, default: Any = None) -> Any:  # noqa: ANN401
    """Read a phase's agent setting from either spelling.

    The packaged workflow YAML nests these under ``agent:`` -- see
    ``workflows/sdlc/research-plan/workflow.yaml`` -- while the create request
    carries them flat. Posting the YAML shape sent the whole block into a key
    nothing read, so the phase installed with no provider and no model, with a
    201 and no warning (#1011).

    A flat field wins when both are present: it is the more specific spelling,
    and picking silently either way would be a guess.
    """
    if name in phase:
        return phase[name]
    agent = phase.get("agent")
    if isinstance(agent, dict) and name in agent:
        return agent[name]
    return default


def _runnable_sandbox(declared: object, phase_id: object) -> str:
    """The phase's sandbox, refused here if a phase cannot finish under it (#1434).

    Checked before the template is persisted, not only at execution: a level
    a phase cannot finish under should never be stored with a 201.
    """
    require_runnable_sandbox(declared, phase_id=None if phase_id is None else str(phase_id))
    return str(declared) if declared else DEFAULT_PHASE_SANDBOX


def _fallback_agent(declared: object) -> FallbackAgent | None:
    """The phase's ``fallback_agent``, held to the YAML's rules, or None (PC-83)."""
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        FallbackAgentYamlDefinition,
    )

    if declared is None:
        return None
    return FallbackAgentYamlDefinition.model_validate(declared).to_domain()


def _build_phase_defs(phases: list[dict[str, Any]] | None) -> list[PhaseDefinition]:
    from syn_domain.contexts.orchestration import PhaseDefinition, PhaseExecutionType

    if phases:
        defs = [
            PhaseDefinition(
                phase_id=p.get("phase_id", str(uuid4())),
                name=p["name"],
                order=p.get("order", i + 1),
                description=p.get("description"),
                execution_type=p.get("execution_type", PhaseExecutionType.SEQUENTIAL),
                input_artifact_types=p.get("input_artifact_types", []),
                output_artifact_types=p.get("output_artifact_types", []),
                prompt_template=p.get("prompt_template"),
                max_tokens=p.get("max_tokens"),
                timeout_seconds=p.get("timeout_seconds"),
                max_cost_usd=p.get("max_cost_usd"),
                allowed_tools=p.get("allowed_tools", []),
                # Dropping this silently reinstates the clone for a phase
                # installed through the API that declared it did not need one
                # (#1187) - the bootstrap cost the declaration exists to avoid.
                clone_repos=_as_bool(p.get("clone_repos", True), "clone_repos"),
                # Dropping this silently re-arms the unpushed-work gate against
                # a phase that declared it delivers no repository changes, so a
                # build tool touching a tracked lockfile fails a phase that did
                # its job (#1308). True is the field's own default, so
                # forgetting it judges the phase strictly rather than leaving
                # it unjudged.
                delivers_repo_changes=_as_bool(
                    p.get("delivers_repo_changes", True), "delivers_repo_changes"
                ),
                argument_hint=p.get("argument_hint"),
                # These four were accepted and discarded (#1011). `provider`
                # meant every codex phase installed through the API ran as
                # claude; `skills` and `claude_plugins` meant per-phase
                # injection installed nothing. The structural test in
                # test_phase_create_carries_every_field.py fails if a future
                # field is added to PhaseDefinition without being mapped here.
                model=_agent_field(p, "model"),
                provider=_agent_field(p, "provider"),
                allow_delegation=_as_bool(
                    _agent_field(p, "allow_delegation", False), "allow_delegation"
                ),
                require_delegation=_as_bool(
                    _agent_field(p, "require_delegation", False), "require_delegation"
                ),
                # Dropping this silently downgrades a phase's declared
                # authority to the default, which for a review phase means it
                # can write the code it certifies (#1161). Caught by the
                # roundtrip assertion in test_phase_create_carries_every_field.
                sandbox=_runnable_sandbox(_agent_field(p, "sandbox"), p.get("phase_id")),
                # Validated by the same model the YAML uses (PC-83), so the API
                # cannot store a fallback the YAML would refuse.
                fallback_agent=_fallback_agent(p.get("fallback_agent")),
                claude_plugins=tuple(p.get("claude_plugins") or ()),
                skills=_expand_skills(p.get("skills")),
            )
            for i, p in enumerate(phases)
        ]
        # The YAML refuses this too; a phase created here never passes it (#1376).
        for d in defs:
            require_enforceable_cost_limit(d.provider, d.max_cost_usd, phase_id=d.phase_id)
            if d.fallback_agent is not None:
                require_enforceable_cost_limit(
                    d.fallback_agent.provider, d.max_cost_usd, phase_id=d.phase_id
                )
        return defs
    return [
        PhaseDefinition(
            phase_id=str(uuid4()),
            name="Initial Phase",
            order=1,
            description="Default initial phase",
        )
    ]


def _build_input_declarations(
    inputs: list[dict[str, Any]] | None,
) -> list[InputDeclaration]:
    from syn_domain.contexts.orchestration import InputDeclaration

    if not inputs:
        return []
    return [
        InputDeclaration(
            name=inp["name"],
            description=inp.get("description"),
            required=inp.get("required", True),
            default=inp.get("default"),
        )
        for inp in inputs
    ]
