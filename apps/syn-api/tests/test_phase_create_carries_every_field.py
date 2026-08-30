"""A phase field the API accepts must reach the domain, or be refused.

`_build_phase_defs` converts an untyped mapping into a `PhaseDefinition`. Because the dict is never validated against a model, a field
it forgets to map is accepted and discarded, and the caller gets 201. Nothing
in the response says the stored workflow differs from the one requested.

Four fields were being dropped when this was written (#1011):

- `provider`, so every codex phase installed through the API silently became a
  claude phase -- including the cross-model review phase, which is the one that
  catches the most defects;
- `allow_delegation`, so cross-harness delegation was silently off;
- `claude_plugins` (#726) and `skills` (#772), so per-phase skill injection
  installed through the API silently injected nothing.

I found `provider` by noticing a workflow run cost 7x less than its
predecessor. The other three were not noticeable at all, which is the argument
for a structural test rather than three more field-specific ones: the failure
mode is silence, so what has to be tested is the MAPPING ITSELF, not each
field's presence one bug at a time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_api.routes.workflows.commands import _build_phase_defs
from syn_domain.contexts.orchestration import PhaseDefinition

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit

#: Fields the create path deliberately does not accept from a caller. Each one
#: needs a reason, because "not mapped" is exactly the bug this test exists to
#: catch -- an empty exemption list is the healthy state.
_NOT_CALLER_SETTABLE: dict[str, str] = {}


def test_every_phase_definition_field_is_mapped_by_create() -> None:
    """The structural guard. Adding a field to `PhaseDefinition` without
    mapping it here fails immediately, rather than shipping and being
    discovered when someone notices a workflow behaving unlike its YAML."""
    source = Path(_build_phase_defs.__code__.co_filename).read_text()
    block = source[
        source.index("def _build_phase_defs") : source.index("def _build_input_declarations")
    ]
    mapped = set(re.findall(r"^\s+(\w+)=", block, re.M))

    unmapped = set(PhaseDefinition.model_fields) - mapped - set(_NOT_CALLER_SETTABLE)

    assert not unmapped, (
        f"{sorted(unmapped)} exist on PhaseDefinition but are never mapped in "
        "_build_phase_defs, so the create endpoint accepts them and returns 201 "
        "while storing a workflow that differs from the request. Either map "
        "them, or add them to _NOT_CALLER_SETTABLE with a reason."
    )


class TestTheFieldsThatWereActuallyDropped:
    """One case per dropped field, so a regression names itself.

    The structural test above catches the class; these say what broke.
    """

    def _phase(self, **extra: object) -> Mapping[str, object]:
        return {"phase_id": "review", "name": "Review", "order": 1, **extra}

    def test_provider_reaches_the_domain(self) -> None:
        """Without this, `codex` phases installed via the API run as claude."""
        (phase,) = _build_phase_defs([self._phase(provider="codex")])
        assert phase.provider == "codex"

    def test_model_still_reaches_the_domain(self) -> None:
        """The one field that DID survive. Kept so a refactor cannot trade one
        dropped field for another."""
        (phase,) = _build_phase_defs([self._phase(model="gpt-5.6-sol")])
        assert phase.model == "gpt-5.6-sol"

    def test_allow_delegation_reaches_the_domain(self) -> None:
        (phase,) = _build_phase_defs([self._phase(allow_delegation=True)])
        assert phase.allow_delegation is True

    def test_an_absent_provider_stays_none(self) -> None:
        """The negative control: mapping must not invent a default. `None`
        means "use the execution default", and a phase that never asked for a
        provider must keep meaning that."""
        (phase,) = _build_phase_defs([self._phase()])
        assert phase.provider is None
        assert phase.allow_delegation is False


class TestTheNestedAgentSpellingIsUnderstood:
    """Our own packaged workflow YAML nests these under `agent:`.

    `workflows/sdlc/research-plan/workflow.yaml` writes
    `agent: {provider: codex, model: gpt-5.6-sol}`. Posting that shape sent
    the whole block into a key nothing reads, so the phase installed with no
    provider AND no model -- silently, with a 201.
    """

    def test_agent_provider_and_model_are_read(self) -> None:
        (phase,) = _build_phase_defs(
            [
                {
                    "phase_id": "review",
                    "name": "Review",
                    "order": 1,
                    "agent": {"provider": "codex", "model": "gpt-5.6-sol"},
                }
            ]
        )
        assert phase.provider == "codex"
        assert phase.model == "gpt-5.6-sol"

    def test_a_flat_field_wins_over_the_nested_block(self) -> None:
        """Both spellings present is a caller error, and resolving it silently
        either way is a guess. The explicit top-level field is the one the
        caller wrote last, so it wins -- stated here rather than left to
        whichever `dict` lookup happens to run first."""
        (phase,) = _build_phase_defs(
            [
                {
                    "phase_id": "review",
                    "name": "Review",
                    "order": 1,
                    "provider": "claude",
                    "agent": {"provider": "codex"},
                }
            ]
        )
        assert phase.provider == "claude"

    def test_an_agent_block_without_the_keys_changes_nothing(self) -> None:
        (phase,) = _build_phase_defs(
            [{"phase_id": "r", "name": "R", "order": 1, "agent": {"allow_delegation": True}}]
        )
        assert phase.provider is None
        assert phase.allow_delegation is True
