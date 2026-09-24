"""Phase model defaults are applied at install and PERSISTED (R1).

The default a phase gets when it declares no model comes from settings
(``SYN_DEFAULT_CLAUDE_MODEL`` / ``SYN_DEFAULT_CODEX_MODEL``), handed to the
install handler as ``PhaseModelDefaults``. The hazard this pins: if the
default were resolved on read instead, changing the setting would silently
rewrite what every existing template replays to. So the chosen model must be
in the event, and a rehydrated aggregate must not care what the setting is
today.

The repository double REPLAYS the stream on every load (see
``InMemoryWorkflowRepository``), so "rehydrate" here is a real replay, not a
cached object.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.test_create_workflow_template import (
    InMemoryEventPublisher,
    InMemoryWorkflowRepository,
)
from syn_shared.agents import AgentProvider, CodexModelAlias, ModelAlias, PhaseModelDefaults

SETTING_A = PhaseModelDefaults(claude=ModelAlias.OPUS, codex=CodexModelAlias.GPT_SOL)
SETTING_B = PhaseModelDefaults(claude=ModelAlias.SONNET, codex="gpt-some-other")


def _command(
    aggregate_id: str,
    *,
    claude_model: str | None = None,
    codex_model: str | None = None,
    version: str | None = "1.0.0",
) -> CreateWorkflowTemplateCommand:
    return CreateWorkflowTemplateCommand(
        aggregate_id=aggregate_id,
        name="Defaults",
        workflow_type=WorkflowType.CUSTOM,
        classification=WorkflowClassification.SIMPLE,
        version=version,
        phases=[
            PhaseDefinition(phase_id="write", name="Write", order=1, model=claude_model),
            PhaseDefinition(
                phase_id="review",
                name="Review",
                order=2,
                provider=AgentProvider.CODEX,
                model=codex_model,
            ),
        ],
    )


def _handler(
    repository: InMemoryWorkflowRepository, defaults: PhaseModelDefaults
) -> CreateWorkflowTemplateHandler:
    return CreateWorkflowTemplateHandler(
        repository, InMemoryEventPublisher(), model_defaults=defaults
    )


async def _models(repository: InMemoryWorkflowRepository, aggregate_id: str) -> list[str | None]:
    aggregate = await repository.get_by_id(aggregate_id)
    assert aggregate is not None
    return [phase.model for phase in aggregate.phases]


@pytest.mark.unit
class TestDefaultsArePersisted:
    @pytest.mark.asyncio
    async def test_undeclared_models_get_the_per_provider_default(self) -> None:
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(_command("wf"))

        assert await _models(repository, "wf") == [ModelAlias.OPUS, CodexModelAlias.GPT_SOL]

    @pytest.mark.asyncio
    async def test_the_default_is_in_the_event_not_resolved_on_read(self) -> None:
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(_command("wf"))

        [envelope] = repository.streams["wf"]
        phases = envelope.event.phases  # type: ignore[attr-defined]
        assert [p.model for p in phases] == [ModelAlias.OPUS, CodexModelAlias.GPT_SOL]

    @pytest.mark.asyncio
    async def test_changing_the_setting_does_not_rewrite_an_existing_template(self) -> None:
        """Create under A, 'change the setting' to B, replay: still A."""
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(_command("wf"))

        # A handler under setting B exists, but replay never consults it.
        _handler(repository, SETTING_B)

        assert await _models(repository, "wf") == [ModelAlias.OPUS, CodexModelAlias.GPT_SOL]

    @pytest.mark.asyncio
    async def test_a_new_template_picks_up_the_new_setting(self) -> None:
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(_command("old"))
        await _handler(repository, SETTING_B).handle(_command("new"))

        assert await _models(repository, "old") == [ModelAlias.OPUS, CodexModelAlias.GPT_SOL]
        assert await _models(repository, "new") == [ModelAlias.SONNET, "gpt-some-other"]

    @pytest.mark.asyncio
    async def test_an_explicit_model_is_never_replaced(self) -> None:
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_B).handle(
            _command("wf", claude_model=ModelAlias.HAIKU, codex_model="gpt-5.6-terra")
        )

        assert await _models(repository, "wf") == [ModelAlias.HAIKU, "gpt-5.6-terra"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_a_blank_model_counts_as_undeclared(self, blank: str) -> None:
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(
            _command("wf", claude_model=blank, codex_model=blank)
        )

        assert await _models(repository, "wf") == [ModelAlias.OPUS, CodexModelAlias.GPT_SOL]

    @pytest.mark.asyncio
    async def test_a_new_version_takes_the_current_setting(self) -> None:
        """An update is a new definition, so it resolves under today's setting."""
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(_command("wf", version="1.0.0"))
        await _handler(repository, SETTING_B).handle(_command("wf", version="2.0.0"))

        assert await _models(repository, "wf") == [ModelAlias.SONNET, "gpt-some-other"]


@pytest.mark.unit
class TestReinstallStaysIdempotent:
    """Persisting defaults must not break #822's no-op reinstall."""

    @pytest.mark.asyncio
    async def test_identical_reinstall_under_the_same_setting_is_a_no_op(self) -> None:
        repository = InMemoryWorkflowRepository()
        handler = _handler(repository, SETTING_A)
        await handler.handle(_command("wf"))

        outcome = await handler.handle(_command("wf"))

        assert outcome.changed is False
        assert len(repository.streams["wf"]) == 1

    @pytest.mark.asyncio
    async def test_identical_reinstall_after_the_setting_changed_is_a_no_op(self) -> None:
        """Without judging identity against the stored models, this would be
        refused as 'version already installed' - the package did not change,
        only the operator's default did."""
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(_command("wf"))

        outcome = await _handler(repository, SETTING_B).handle(_command("wf"))

        assert outcome.changed is False
        assert await _models(repository, "wf") == [ModelAlias.OPUS, CodexModelAlias.GPT_SOL]

    @pytest.mark.asyncio
    async def test_a_template_stored_before_defaults_were_persisted_stays_installable(
        self,
    ) -> None:
        """A legacy stream holds model=None. Reinstalling the same package is
        still a no-op, and the stored None keeps resolving via the domain's
        static fallback at execution time."""
        repository = InMemoryWorkflowRepository()
        legacy = _command("wf")
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
            WorkflowTemplateAggregate,
        )

        aggregate = WorkflowTemplateAggregate()
        aggregate.create_workflow(legacy)  # the pre-change path: no defaults applied
        await repository.save(aggregate)
        assert await _models(repository, "wf") == [None, None]

        outcome = await _handler(repository, SETTING_A).handle(_command("wf"))

        assert outcome.changed is False
        assert await _models(repository, "wf") == [None, None]

    @pytest.mark.asyncio
    async def test_a_changed_explicit_model_is_still_a_change(self) -> None:
        """The stored-model fill applies only to UNDECLARED models."""
        repository = InMemoryWorkflowRepository()
        await _handler(repository, SETTING_A).handle(_command("wf", version="1.0.0"))

        outcome = await _handler(repository, SETTING_A).handle(
            _command("wf", claude_model=ModelAlias.HAIKU, version="2.0.0")
        )

        assert outcome.changed is True
        assert await _models(repository, "wf") == [ModelAlias.HAIKU, CodexModelAlias.GPT_SOL]
