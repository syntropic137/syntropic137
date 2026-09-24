"""A phase edit normalises the provider/model pair it records (review pass 2).

Install already resolves a phase's model for its provider. A phase edit is
the other write boundary, and without the same rule it persisted the old
provider's model across a provider switch (``opus`` on a codex phase) and
kept a legacy ``model=None`` through every edit. The stored template - and so
its export - was wrong even when execution happened to correct it.

Every case reloads the aggregate from the replayed stream, so what is asserted
is what the events say, not an in-memory object.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.UpdatePhasePromptCommand import (
    UpdatePhasePromptCommand,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.test_create_workflow_template import (
    InMemoryEventPublisher,
    InMemoryWorkflowRepository,
)
from syn_domain.contexts.orchestration.slices.update_workflow_phase.UpdateWorkflowPhaseHandler import (
    UpdateWorkflowPhaseHandler,
)
from syn_shared.agents import (
    AgentProvider,
    CodexModelAlias,
    ModelAlias,
    ModelId,
    PhaseModelDefaults,
)

pytestmark = pytest.mark.unit

#: Operator settings deliberately unlike the static fallbacks, so a test can
#: tell "configured default" from "static fallback".
CONFIGURED = PhaseModelDefaults(claude=ModelAlias.SONNET, codex="gpt-operator-choice")


def _phase(provider: str | None, model: str | None) -> PhaseDefinition:
    return PhaseDefinition(
        phase_id="p", name="P", order=1, prompt_template="old", provider=provider, model=model
    )


async def _installed(phase: PhaseDefinition) -> InMemoryWorkflowRepository:
    repository = InMemoryWorkflowRepository()
    await CreateWorkflowTemplateHandler(
        repository, InMemoryEventPublisher(), model_defaults=CONFIGURED
    ).handle(
        CreateWorkflowTemplateCommand(
            aggregate_id="wf",
            name="Edit",
            workflow_type=WorkflowType.CUSTOM,
            classification=WorkflowClassification.SIMPLE,
            phases=[phase],
        )
    )
    return repository


async def _legacy(phase: PhaseDefinition) -> InMemoryWorkflowRepository:
    """A stream written before install normalised anything."""
    repository = InMemoryWorkflowRepository()
    aggregate = WorkflowTemplateAggregate()
    aggregate.create_workflow(
        CreateWorkflowTemplateCommand(
            aggregate_id="wf",
            name="Edit",
            workflow_type=WorkflowType.CUSTOM,
            classification=WorkflowClassification.SIMPLE,
            phases=[phase],
        )
    )
    await repository.save(aggregate)
    return repository


async def _edit(
    repository: InMemoryWorkflowRepository,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str | None, str | None, bool]:
    await UpdateWorkflowPhaseHandler(
        repository, InMemoryEventPublisher(), model_defaults=CONFIGURED
    ).handle(
        UpdatePhasePromptCommand(
            aggregate_id="wf", phase_id="p", prompt_template="new", provider=provider, model=model
        )
    )
    aggregate = await repository.get_by_id("wf")
    assert aggregate is not None
    (phase,) = aggregate.phases
    assert phase.prompt_template == "new"
    return phase.provider, phase.model, phase.model_defaulted


class TestProviderSwitch:
    async def test_claude_to_codex_replaces_the_defaulted_claude_model(self) -> None:
        repository = await _installed(_phase(None, None))

        assert await _edit(repository, provider=AgentProvider.CODEX) == (
            AgentProvider.CODEX,
            CONFIGURED.codex,
            True,
        )

    async def test_codex_to_claude_replaces_the_defaulted_codex_model(self) -> None:
        """The configured codex default is a string the table cannot judge, so
        only provenance can say it must not survive the switch."""
        repository = await _installed(_phase(AgentProvider.CODEX, None))

        assert await _edit(repository, provider=AgentProvider.CLAUDE) == (
            AgentProvider.CLAUDE,
            CONFIGURED.claude,
            True,
        )

    async def test_a_declared_model_of_the_old_provider_is_replaced(self) -> None:
        repository = await _installed(_phase(AgentProvider.CODEX, ModelId.GPT_5_6_TERRA))

        assert await _edit(repository, provider=AgentProvider.CLAUDE) == (
            AgentProvider.CLAUDE,
            CONFIGURED.claude,
            True,
        )

    async def test_a_model_named_with_the_switch_is_kept(self) -> None:
        repository = await _installed(_phase(None, None))

        assert await _edit(
            repository, provider=AgentProvider.CODEX, model=ModelId.GPT_5_6_TERRA
        ) == (AgentProvider.CODEX, ModelId.GPT_5_6_TERRA, False)

    async def test_an_unjudgeable_declared_model_is_carried_across(self) -> None:
        """Declared, and not in the platform's vocabulary: it cannot be proven
        wrong, so it is kept rather than replaced on a guess."""
        repository = await _installed(_phase(AgentProvider.CODEX, "gpt-future-slug"))

        assert await _edit(repository, provider=AgentProvider.CLAUDE) == (
            AgentProvider.CLAUDE,
            "gpt-future-slug",
            False,
        )


class TestWrongProviderModels:
    @pytest.mark.parametrize(
        ("provider", "model", "expected"),
        [
            (AgentProvider.CODEX, ModelAlias.OPUS, CONFIGURED.codex),
            (AgentProvider.CODEX, ModelId.CLAUDE_OPUS_5_5, CONFIGURED.codex),
            (AgentProvider.CLAUDE, CodexModelAlias.GPT_SOL, CONFIGURED.claude),
            (AgentProvider.CLAUDE, ModelId.GPT_6_SOL, CONFIGURED.claude),
        ],
    )
    async def test_an_edit_naming_a_wrong_provider_model_gets_the_default(
        self, provider: str, model: str, expected: str
    ) -> None:
        repository = await _installed(_phase(provider, None))

        assert await _edit(repository, model=model) == (provider, expected, True)

    @pytest.mark.parametrize(
        ("provider", "model"),
        [
            (AgentProvider.CODEX, ModelId.GPT_6_SOL),
            (AgentProvider.CODEX, CodexModelAlias.GPT_SOL),
            (AgentProvider.CLAUDE, ModelId.CLAUDE_OPUS_5_5),
            (AgentProvider.CLAUDE, ModelAlias.HAIKU),
        ],
    )
    async def test_a_right_provider_model_is_kept_as_declared(
        self, provider: str, model: str
    ) -> None:
        repository = await _installed(_phase(provider, None))

        assert await _edit(repository, model=model) == (provider, model, False)


class TestLegacyAndPromptOnlyEdits:
    async def test_a_prompt_only_edit_keeps_a_declared_model(self) -> None:
        repository = await _installed(_phase(None, ModelAlias.HAIKU))

        assert await _edit(repository) == (None, ModelAlias.HAIKU, False)

    async def test_a_legacy_none_model_gets_the_configured_default(self) -> None:
        repository = await _legacy(_phase(AgentProvider.CODEX, None))

        assert await _edit(repository) == (AgentProvider.CODEX, CONFIGURED.codex, True)

    async def test_a_legacy_wrong_provider_model_is_corrected(self) -> None:
        repository = await _legacy(_phase(AgentProvider.CODEX, ModelAlias.HAIKU))

        assert await _edit(repository) == (AgentProvider.CODEX, CONFIGURED.codex, True)

    async def test_a_blank_model_in_the_edit_means_keep(self) -> None:
        repository = await _installed(_phase(None, ModelAlias.HAIKU))

        assert await _edit(repository, model="  ") == (None, ModelAlias.HAIKU, False)


class TestPromptOnlyEditKeepsProvenance:
    """Codex review pass 3: an edit that does not touch the model must not
    relabel a stored default as declared."""

    async def test_the_default_flag_survives_a_prompt_only_edit(self) -> None:
        repository = await _installed(_phase(None, None))

        assert await _edit(repository) == (None, CONFIGURED.claude, True)

    async def test_an_unchanged_reinstall_after_a_prompt_edit_is_a_no_op(self) -> None:
        repository = await _installed(_phase(None, None))
        await _edit(repository)

        outcome = await CreateWorkflowTemplateHandler(
            repository, InMemoryEventPublisher(), model_defaults=CONFIGURED
        ).handle(
            CreateWorkflowTemplateCommand(
                aggregate_id="wf",
                name="Edit",
                workflow_type=WorkflowType.CUSTOM,
                classification=WorkflowClassification.SIMPLE,
                phases=[
                    _phase(None, None).model_copy(update={"prompt_template": "new"}),
                ],
            )
        )

        assert outcome.changed is False
