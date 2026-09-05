"""A declared field must be applied or refused, never dropped (#1039, ADR-069 D5).

Four fields were validated, persisted, projected, re-exported as YAML, and then
dropped before execution. ``ExecutablePhase`` has exactly one production
construction site (``ExecuteWorkflowHandler._build_executable_phases``), so
anything not passed
there is inert by construction.

The four are NOT one change, and this module is organised by the decision taken
for each rather than by field:

- ``allowed_tools``   APPLY.  It has a runtime slot and a live emit path.
- ``execution_type``  REFUSE. Neither ``parallel`` nor ``human_in_loop`` has an
                              implementation, and nothing in the codebase
                              branches on the field at all.
- ``argument_hint``   KEEP.   Looks inert and is not: the dashboard renders it.
                              Display metadata, never execution config.
- ``input_artifacts`` REFUSE. It cannot be applied: see the class docstring on
                              TestInputArtifactsAreValidatedNotFiltered.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from syn_shared.agents import AgentProvider
from syn_shared.tools import ToolName

pytestmark = pytest.mark.unit


def _phase(**overrides):
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        PhaseYamlDefinition,
    )

    payload = {"id": "research", "name": "research", "order": 1, "prompt_template": "do the thing"}
    payload.update(overrides)
    return PhaseYamlDefinition(**payload)


def _workflow(phases, inputs=None):
    """Build a WorkflowDefinition from raw phase mappings.

    Deliberately unannotated, matching `_phase` above. An explicit untyped
    mapping annotation trips the untyped-dict ratchet (`just
    check-untyped-dicts`, which matches raw text and so counts a mention in a
    comment too), and the payload is a YAML-shaped mapping on its way into
    `model_validate` rather than a typed structure worth naming.
    """
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        WorkflowDefinition,
    )

    payload = {"id": "wf-1", "name": "wf", "type": "research", "phases": phases}
    if inputs is not None:
        payload["inputs"] = inputs
    return WorkflowDefinition.model_validate(payload)


@dataclass
class _StoredPhaseDeclaring:
    """A rehydrated phase that declared exactly the fields passed here.

    Duck-typed on purpose, and ``sandbox`` defaults to None rather than to
    ``DEFAULT_PHASE_SANDBOX``. Both are needed for the early-return branch in
    ``_build_agent_config_from_phase`` to be reachable AT ALL:

    - It reads its input with ``getattr(phase, ..., default)``, so it accepts
      any object, which is how a rehydrated template reaches it.
    - ``PhaseDefinition.sandbox`` is a non-optional ``str`` with a non-null
      default, and ``PhaseYamlDefinition.to_domain()`` substitutes
      ``DEFAULT_PHASE_SANDBOX`` when the YAML omits it. So for EVERY real
      phase object the predicate's ``sandbox is not None`` term is true, the
      predicate is true, and no test built from one can observe which other
      terms it contains.

    That is not a hypothetical (#1207): the canary below asserted nothing for
    a full release because of it. Declaring one field here and nothing else is
    the only shape that makes the predicate answer False, so it is the only
    shape that can pin what the predicate reads.
    """

    model: str | None = None
    provider: str | None = None
    allow_delegation: bool = False
    allowed_tools: tuple[str, ...] = ()
    sandbox: str | None = None
    phase_id: str = "research"


class TestAllowedToolsReachesExecution:
    """APPLY. The emit path already existed; only the hand-off was missing.

    ``_build_agent_config_from_phase`` built ``AgentConfiguration`` from three
    fields, so ``allowed_tools`` kept its default of ``()``, the
    ``if phase.agent_config.allowed_tools:`` guard in ``_build_claude_command``
    never fired, and ``--tools`` was never passed to any phase. That also left the codex refusal and the #964 vocabulary validator
    enforcing nothing.
    """

    def test_declared_tools_reach_the_agent_configuration(self) -> None:
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )

        phase = _phase(allowed_tools=["Bash", "Read"], model="haiku").to_domain()

        config = _build_agent_config_from_phase(phase)

        assert config.allowed_tools == (ToolName.BASH, ToolName.READ)

    def test_tools_survive_when_they_are_the_only_thing_declared(self) -> None:
        """The early-return trap, and the reason this is not a one-line fix.

        ``if not (phase_model or phase_provider or allow_delegation): return
        defaults`` fired BEFORE the constructor. So adding ``allowed_tools`` to
        the constructor alone would still drop it for exactly the phases most
        likely to declare it: a phase that scopes its tools and accepts the
        default model and provider. This is the regression that a
        constructor-only fix passes and production does not.

        WHY THE FIXTURE IS ``_StoredPhaseDeclaring`` AND NOT ``.to_domain()``
        (#1207). This test spent a release asserting nothing. It built its
        phase through ``PhaseYamlDefinition.to_domain()``, which substitutes
        ``DEFAULT_PHASE_SANDBOX`` for an undeclared sandbox, so the predicate's
        ``sandbox is not None`` term was unconditionally true and the test
        passed with ``allowed_tools`` deleted from the predicate entirely - the
        one mutation it exists to catch. A canary that cannot go quiet is not a
        canary. See ``_StoredPhaseDeclaring`` for why no ``PhaseDefinition``
        can reach the branch either.
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )

        config = _build_agent_config_from_phase(_StoredPhaseDeclaring(allowed_tools=("Bash",)))

        assert config.allowed_tools == (ToolName.BASH,), "dropped by the early-return branch"

    @pytest.mark.parametrize(
        ("field", "declared", "expected"),
        [
            ("model", "haiku", "haiku"),
            ("provider", AgentProvider.CODEX, AgentProvider.CODEX),
            ("allow_delegation", True, True),
            ("allowed_tools", ("Bash",), (ToolName.BASH,)),
            ("sandbox", "read-only", "read-only"),
        ],
    )
    def test_every_field_the_predicate_gates_survives_being_declared_alone(
        self, field: str, declared: object, expected: object
    ) -> None:
        """The whole class of bug, not just the instance that cost a release.

        ``_phase_declares_anything`` duplicates knowledge that the constructor
        below it already has: the set of fields a phase can declare. Whenever
        those two lists disagree, the field missing from the PREDICATE is
        dropped for the one author who declared only it - silently, because the
        early return hands back a fully-formed default config rather than
        failing. That is #1039 (``allowed_tools``) and #1207 (the canary that
        could not see it) as a single shape.

        So each field is declared ALONE here. Delete any one term from the
        predicate and exactly one of these cases goes red, naming the field.
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )

        config = _build_agent_config_from_phase(_StoredPhaseDeclaring(**{field: declared}))

        assert getattr(config, field) == expected, f"{field} dropped by the early-return branch"

    def test_a_phase_declaring_no_tools_still_gets_the_full_toolset(self) -> None:
        """Absence means absence (ADR-069 D4), not an empty grant."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )

        config = _build_agent_config_from_phase(_phase().to_domain())

        assert config.allowed_tools == ()


class TestExecutionTypeIsRefusedUntilItIsImplemented:
    """REFUSE. Nothing in the codebase branches on this field.

    A grep for ``PhaseExecutionType.PARALLEL`` / ``.HUMAN_IN_LOOP`` outside
    the enum definition returns nothing: no processor, no dispatcher, no
    handler. Wiring ``parallel`` without a parallel processor would convert a
    silent lie into a crash, so it is refused at authoring time instead.

    ``human_in_loop`` is refused in the SAME change rather than left for later.
    It is the same defect and the more dangerous half: an author who writes it
    believes a human approves the phase before it runs, and no human does.
    Fixing one and not the other would certify the open half as closed.
    """

    @pytest.mark.parametrize("declared", ["parallel", "human_in_loop"])
    def test_an_unimplemented_execution_type_is_refused(self, declared: str) -> None:
        with pytest.raises(ValidationError) as exc:
            _phase(execution_type=declared)

        assert declared in str(exc.value)

    def test_sequential_is_accepted_because_it_is_what_actually_happens(self) -> None:
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
            PhaseExecutionType,
        )

        assert _phase(execution_type="sequential").execution_type is PhaseExecutionType.SEQUENTIAL

    def test_omitting_it_is_accepted_and_means_sequential(self) -> None:
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
            PhaseExecutionType,
        )

        assert _phase().execution_type is PhaseExecutionType.SEQUENTIAL


class TestArgumentHintIsDisplayMetadata:
    """KEEP. This one is NOT inert, and the first read of it was wrong.

    `argument_hint` looks exactly like the other three: it sits in the
    `# Claude Code command extensions (ISS-211)` block, it is slash-command
    frontmatter by lineage, and it never reaches execution. Reasoning from that
    lineage says "no consumer, delete it".

    It has a consumer. `apps/syn-dashboard-ui/src/pages/WorkflowDetail/
    PhasePromptEditor.tsx:36` renders it beside the prompt, and the domain
    docstring calls it "Describes what $ARGUMENTS expects for this phase". So
    it is not a field that is dropped on the way to execution; it is a field
    that was never meant to reach execution and arrives where it is used.

    The lesson generalises to the D5 fitness rule: "applied" cannot mean "reaches
    the agent command", or the rule deletes every legitimately non-execution
    field. Display is a fate. See the `_DISPLAYED` table in
    ci/fitness/api/test_phase_schema_fields_apply_or_refuse.py.
    """

    def test_it_is_accepted_and_carried_to_the_domain(self) -> None:
        phase = _phase(argument_hint="[feature-request]")

        assert phase.argument_hint == "[feature-request]"
        assert phase.to_domain().argument_hint == "[feature-request]"

    def test_omitting_it_is_fine(self) -> None:
        assert _phase().argument_hint is None


class TestInputArtifactsAreValidatedNotFiltered:
    """REFUSE. The declaration cannot be applied, because there is no join key.

    Measured across all 22 authored multi-phase workflows before this was
    designed:

    - injection is keyed on PHASE IDs. ``_substitute_inputs`` substitutes
      ``{{<phase-id>}}`` and ``_build_context_appendix`` keys the appendix by
      phase id.
    - declaration is keyed on ARTIFACT TYPES
      (``workflow_definition.py`` maps ``input_artifacts`` ->
      ``input_artifact_types``).
    - the intersection of the two vocabularies over the whole corpus is the
      EMPTY SET. 0 declared inputs equal a phase id; 31 equal a prior phase's
      declared output type.

    So filtering ``phase_outputs`` by ``input_artifacts`` would filter a
    phase-id-keyed dict by names that provably never match a phase id, and
    every phase would receive nothing. That is not a compatibility risk to be
    sized, it is guaranteed total breakage, and 8 phases hard-depend on the
    phase-id channel.

    What authors actually wrote is coherent: a type-level dependency graph.
    So the field keeps its meaning and becomes a checked assertion. Runtime
    injection is untouched.
    """

    def test_an_input_produced_by_an_earlier_phase_is_accepted(self) -> None:
        wf = _workflow(
            [
                {
                    "id": "discovery",
                    "name": "d",
                    "order": 1,
                    "prompt_template": "x",
                    "output_artifacts": ["research_scope"],
                },
                {
                    "id": "synthesis",
                    "name": "s",
                    "order": 2,
                    "prompt_template": "x",
                    "input_artifacts": ["research_scope"],
                },
            ]
        )

        assert wf.phases[1].input_artifacts == ["research_scope"]

    def test_an_input_no_phase_produces_is_refused(self) -> None:
        """The real bug this catches, found in a shipped workflow.

        ``examples/implementation.yaml`` declares ``feature_request`` as an
        input to two phases. No phase outputs it and the workflow's only
        declared input is ``task``. It resolves to nothing, and while the field
        was inert nothing noticed.
        """
        with pytest.raises(ValidationError) as exc:
            _workflow(
                [
                    {
                        "id": "research",
                        "name": "r",
                        "order": 1,
                        "prompt_template": "x",
                        "input_artifacts": ["feature_request"],
                    },
                ]
            )

        message = str(exc.value)
        assert "feature_request" in message
        assert "research" in message

    def test_a_workflow_level_input_satisfies_the_declaration(self) -> None:
        wf = _workflow(
            [
                {
                    "id": "research",
                    "name": "r",
                    "order": 1,
                    "prompt_template": "x",
                    "input_artifacts": ["task"],
                },
            ],
            inputs=[{"name": "task", "description": "the task", "required": True}],
        )

        assert wf.phases[0].input_artifacts == ["task"]

    def test_a_later_phases_output_does_not_satisfy_an_earlier_phase(self) -> None:
        """Ordering is load-bearing: a phase cannot consume the future."""
        with pytest.raises(ValidationError) as exc:
            _workflow(
                [
                    {
                        "id": "first",
                        "name": "f",
                        "order": 1,
                        "prompt_template": "x",
                        "input_artifacts": ["late_result"],
                    },
                    {
                        "id": "second",
                        "name": "s",
                        "order": 2,
                        "prompt_template": "x",
                        "output_artifacts": ["late_result"],
                    },
                ]
            )

        assert "late_result" in str(exc.value)


class TestCodexRefusesToolPoliciesAtAuthoringTime:
    """The refusal existed and was unreachable; it also fired far too late.

    ``UnsupportedToolPolicyError`` was raised from the command builder, behind
    ``if phase.agent_config.allowed_tools:`` - the tuple that was always empty.
    Making ``allowed_tools`` live makes it reachable, but dispatch is the wrong
    place: by then the workspace is provisioned and paid for. Codex has no tool
    vocabulary at all (ADR-069 section 3), so the answer cannot change between
    authoring and dispatch. Refuse at creation.
    """

    def test_codex_with_declared_tools_is_refused_when_the_workflow_is_written(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _phase(
                allowed_tools=["Bash"],
                agent={"provider": AgentProvider.CODEX},
            )

        message = str(exc.value)
        assert "codex" in message.lower()
        assert "Bash" in message

    def test_codex_without_declared_tools_is_fine(self) -> None:
        phase = _phase(agent={"provider": AgentProvider.CODEX})

        assert phase.allowed_tools == []

    def test_claude_with_declared_tools_is_fine(self) -> None:
        phase = _phase(allowed_tools=["Bash"], agent={"provider": AgentProvider.CLAUDE})

        assert phase.allowed_tools == [ToolName.BASH]


class TestStoredTemplatesAreCheckedAtTheExecutionBoundary:
    """Authoring-time refusal is NOT sufficient, and this is the load-bearing half.

    A template stored before a rule existed is rehydrated straight from its
    historical ``WorkflowTemplateCreated`` event and never sees the YAML
    validator - the reason ``require_executable_provider`` already guards
    execution rather than parsing alone. A loader-only check protects new and
    reinstalled workflows and misses every workflow already installed, which is
    the population most likely to carry the bad value.

    These are not duplicates of the authoring tests above. They construct a
    phase object directly, bypassing the schema exactly as rehydration does.
    """

    def test_an_unimplemented_execution_type_is_refused_at_execution(self) -> None:
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
            UnsupportedExecutionTypeError,
            require_supported_execution_type,
        )

        with pytest.raises(UnsupportedExecutionTypeError) as exc:
            require_supported_execution_type("parallel", phase_id="p1")

        assert "parallel" in str(exc.value)
        assert "p1" in str(exc.value)

    def test_a_tool_name_outside_the_vocabulary_is_refused_at_execution(self) -> None:
        """The real deployment case, and why this refuses instead of dropping.

        11 phases across 4 installed workflows declare ``git``, which is not a
        tool on any harness. Silently dropping it would restrict those phases
        to ``Bash`` alone and remove every other tool they use - a failure that
        looks like the agent got worse rather than like a bad declaration.
        """
        from syn_shared.tools import UnsupportedToolNameError, require_supported_tools

        with pytest.raises(UnsupportedToolNameError) as exc:
            require_supported_tools(["bash", "git", "read"], phase_id="ci-fix")

        message = str(exc.value)
        assert "git" in message
        assert "ci-fix" in message

    def test_a_valid_stored_declaration_canonicalises(self) -> None:
        """Case is still forgiven; only unknown names are refused."""
        from syn_shared.tools import require_supported_tools

        assert require_supported_tools(["bash", "read"]) == (ToolName.BASH, ToolName.READ)

    def test_codex_with_stored_tools_is_refused_before_provisioning(self) -> None:
        """Two installed workflows carry this shape.

        The command builder already refused it, but only after the workspace
        was provisioned and paid for. This fires at the execution boundary.
        """
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
            PhaseDefinition,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
            UnsupportedToolPolicyForProviderError,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )

        # Built as the aggregate rehydrates it, NOT through PhaseYamlDefinition:
        # the schema now refuses this shape, which is exactly why a stored
        # template can still carry it.
        stored = PhaseDefinition(
            phase_id="build-and-delegate",
            name="Build and delegate",
            order=1,
            provider=AgentProvider.CODEX,
            allowed_tools=["Read", "Grep"],
        )

        with pytest.raises(UnsupportedToolPolicyForProviderError) as exc:
            _build_agent_config_from_phase(stored)

        assert "codex" in str(exc.value).lower()


class TestTheVocabularyOnlyAcceptsNamesTheCliActuallyGrants:
    """#1207. A name the CLI does not grant is worse than an unknown name.

    ``LS``, ``TodoRead``, ``TodoWrite`` and ``MultiEdit`` were in the
    vocabulary, sourced from a stale image manifest. The CLI grants none of
    them: ``claude -p --tools LS`` reports ``tools: []``. So a phase declaring
    one was ACCEPTED here and then ran with no tools at all.

    That is an upgrade break, not a wart. While ``allowed_tools`` was dropped
    (v0.27) such a phase got the full toolset and worked; now that it is
    applied (v0.28) the same stored phase gets nothing. Applied-to-nothing is
    worse than either honouring or refusing it, because it is silent.

    Refusing at the execution boundary is what converts that into an error
    naming the phase, BEFORE a workspace is provisioned and paid for.
    """

    @pytest.mark.parametrize("ungranted", ["LS", "TodoRead", "TodoWrite", "MultiEdit"])
    def test_a_name_the_cli_does_not_grant_is_refused(self, ungranted: str) -> None:
        from syn_shared.tools import UnsupportedToolNameError, require_supported_tools

        with pytest.raises(UnsupportedToolNameError) as exc:
            require_supported_tools([ungranted], phase_id="build-and-delegate")

        message = str(exc.value)
        assert ungranted in message, "the refusal must name what was rejected"
        assert "build-and-delegate" in message, "and which phase to go and fix"
        # The valid set is spelled out, so the author can repair the
        # declaration from the error alone rather than reading our source.
        for valid in ("Bash", "Edit", "Glob", "Grep", "Read", "Skill", "Task", "Write"):
            assert valid in message, f"the error must name {valid} as a valid choice"

    @pytest.mark.parametrize("ungranted", ["LS", "TodoRead", "TodoWrite", "MultiEdit"])
    def test_an_ungranted_name_is_refused_at_authoring_time_too(self, ungranted: str) -> None:
        """Both hops, because they protect different populations.

        The YAML validator catches the next author; the execution boundary
        above catches the templates already stored, which never see it.
        """
        with pytest.raises(ValidationError):
            _phase(allowed_tools=[ungranted])

    def test_skill_is_accepted_because_the_cli_does_grant_it(self) -> None:
        """The other half of #1207: a capability the vocabulary wrongly refused.

        ``claude -p --tools Skill`` reported ``tools: ['Skill']`` on CLI
        2.1.258 run directly in an agent workspace. The pinned image was NOT
        probed because Docker was unavailable; the integration half of
        test_tool_vocabulary_matches_the_cli.py is the still-unrun check of it.
        """
        from syn_shared.tools import require_supported_tools

        assert require_supported_tools(["Skill"]) == (ToolName.SKILL,)

    def test_a_valid_declaration_still_reaches_the_agent_configuration(self) -> None:
        """(b) The negative control: refusing more must not break what worked.

        Asserted on the CONSUMER (``AgentConfiguration``), not on the enum, and
        including ``Skill`` - a tuple this assertion could not have produced
        before this change, because the vocabulary refused that name.
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
            _build_agent_config_from_phase,
        )

        phase = _phase(allowed_tools=["Read", "Skill", "bash"], model="haiku").to_domain()

        config = _build_agent_config_from_phase(phase)

        # Order preserved, case forgiven, nothing dropped.
        assert config.allowed_tools == (ToolName.READ, ToolName.SKILL, ToolName.BASH)


class TestDelegatingTheVocabularyCheckChangedNoBehaviour:
    """`_validate_tool_names` now calls `require_supported_tools` (#1039).

    The rule had to move so execution could apply the SAME one to stored
    templates that never saw the YAML validator; two copies of a vocabulary
    check are two things to drift apart. But a refactor that quietly changes
    how declarations normalise would corrupt every workflow on reinstall, so
    the accepted shapes are pinned here rather than assumed.
    """

    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("Bash,Read", ["Bash", "Read"]),
            ("bash,read", ["Bash", "Read"]),
            (None, []),
            ([], []),
            (["bAsH", "READ"], ["Bash", "Read"]),
            # Duplicates are NOT collapsed, and order is NOT sorted. Both are
            # pre-existing behaviour; changing either would rewrite the `--tools`
            # argument for workflows that never asked for it.
            (["Bash", "Bash", "Read"], ["Bash", "Bash", "Read"]),
            (["Write", "Bash", "Read"], ["Write", "Bash", "Read"]),
        ],
    )
    def test_accepted_shapes_normalise_exactly_as_before(
        self, declared: object, expected: list[str]
    ) -> None:
        assert _phase(allowed_tools=declared).allowed_tools == expected

    @pytest.mark.parametrize("declared", [["git"], [""], ["   "], [3], 42])
    def test_rejected_shapes_are_still_rejected(self, declared: object) -> None:
        with pytest.raises(ValidationError):
            _phase(allowed_tools=declared)
