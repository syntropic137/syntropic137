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

from typing import TYPE_CHECKING

import pytest

from syn_api.routes.workflows.commands import _build_phase_defs
from syn_domain.contexts.orchestration import PhaseDefinition, PhaseExecutionType

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit

#: Fields the create path deliberately does not accept from a caller. Each one
#: needs a reason, because "not mapped" is exactly the bug this test exists to
#: catch -- an empty exemption list is the healthy state.
_NOT_CALLER_SETTABLE: dict[str, str] = {}


#: One distinctive, non-default value per field. The fixture is compared
#: against ``PhaseDefinition.model_fields`` below, so a NEW field on the model
#: fails here until someone decides what a caller should be able to send.
_EVERY_FIELD: Mapping[str, object] = {
    "phase_id": "review",
    "name": "Review",
    "order": 3,
    # NOT the default. "sequential" IS the default, so asserting it proves
    # nothing -- deleting the mapping entirely would still satisfy it. That
    # is the tautology this file exists to avoid, and the first version of
    # this fixture contained it.
    "execution_type": "parallel",
    "description": "a description",
    "input_artifact_types": ["markdown"],
    "output_artifact_types": ["json"],
    "prompt_template": "do the thing",
    "max_tokens": 1234,
    "timeout_seconds": 2400,
    "allowed_tools": ["Read", "Grep"],
    "argument_hint": "[task]",
    "model": "gpt-5.6-sol",
    "provider": "codex",
    "allow_delegation": True,
    "claude_plugins": ["owner/repo@abc123"],
    # Skill refs name a SKILL inside a repo; plugin refs name the repo.
    # The model rejects the plugin spelling here, which is how I learned it.
    "skills": ["owner/repo/some-skill@abc123"],
}


def test_the_fixture_covers_every_field_on_the_model() -> None:
    """A new field on `PhaseDefinition` fails here first.

    Without this, the round-trip below would silently stop covering whatever
    was added -- which is the failure this whole file exists to prevent, one
    level up.
    """
    assert set(_EVERY_FIELD) == set(PhaseDefinition.model_fields)


def test_every_field_a_caller_sends_survives_into_the_domain() -> None:
    """Behavioural, not textual.

    The first version of this test grepped the function body for ``name=``
    and asserted every model field appeared. It was worthless: deleting the
    real ``skills=`` mapping and adding a decoy ``skills=()`` to the
    DEFAULT-phase constructor a few lines below left all eight tests passing.
    A guard that can be satisfied by an unrelated assignment does not measure
    the mapping, and it is worse than no guard because it reads as coverage.

    So this sends a distinctive value for every field and reads the result
    back off the constructed object. Nothing about how the mapping is written
    can satisfy it -- only the value arriving.
    """
    (phase,) = _build_phase_defs([dict(_EVERY_FIELD)])

    assert phase.phase_id == "review"
    assert phase.name == "Review"
    assert phase.order == 3
    assert phase.description == "a description"
    assert phase.input_artifact_types == ["markdown"]
    assert phase.output_artifact_types == ["json"]
    assert phase.prompt_template == "do the thing"
    assert phase.max_tokens == 1234
    assert phase.timeout_seconds == 2400
    assert phase.allowed_tools == ["Read", "Grep"]
    assert phase.argument_hint == "[task]"
    assert phase.model == "gpt-5.6-sol"
    assert phase.provider == "codex"
    assert phase.allow_delegation is True
    # IDENTITY, not cardinality. The previous version asserted `len(...) == 1`
    # while its comment claimed identity was checked -- so an implementation
    # substituting a wholly different plugin passed. Verified: a mutant
    # returning ("wrong/repo@wrong",) satisfied every assertion here.
    assert phase.claude_plugins[0].source_url.endswith("owner/repo")
    assert phase.claude_plugins[0].version == "abc123"
    assert phase.skills[0].skill_name == "some-skill"
    assert phase.skills[0].source_url.endswith("owner/repo")
    assert phase.execution_type == PhaseExecutionType.PARALLEL


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


class TestBooleansAreNotCoerced:
    """`bool("false")` is True, and JSON callers send strings."""

    @pytest.mark.parametrize("sent", ["false", "true", 1, 0, "yes"])
    def test_a_non_boolean_is_rejected_rather_than_guessed(self, sent: object) -> None:
        """Both guesses are wrong, in opposite directions.

        `bool("false")` enabled delegation the caller asked to disable. The
        first fix silently defaulted a non-bool to False, so `1` and `"true"`
        DISABLED delegation the caller asked to enable -- still a 201, still
        altered state. A malformed value is an error, not an opinion.
        """
        with pytest.raises(ValueError, match="must be a boolean"):
            _build_phase_defs(
                [{"phase_id": "r", "name": "R", "order": 1, "allow_delegation": sent}]
            )

    def test_a_real_true_still_enables_it(self) -> None:
        (phase,) = _build_phase_defs(
            [{"phase_id": "r", "name": "R", "order": 1, "allow_delegation": True}]
        )
        assert phase.allow_delegation is True


class TestMultiNameSkillsExpand:
    """`names: [a, b]` declares TWO skills, and shorthand cannot prove it.

    The round-trip fixture sends a shorthand skill string, which validates
    identically whether or not expansion runs -- so removing expansion killed
    no test. The verbose form is the only shape where the two paths differ,
    which makes it the only shape that measures this.
    """

    def test_two_names_become_two_skills(self) -> None:
        """Passing the entry straight to `SkillRef` produced ONE skill named
        after the repo. A caller asking for `alpha` and `beta` got a single
        skill called `b`: a wrong identity, which resolves and injects the
        wrong instructions. `main` merely dropped skills -- absent is
        recoverable, wrong is not."""
        (phase,) = _build_phase_defs(
            [
                {
                    "phase_id": "r",
                    "name": "R",
                    "order": 1,
                    "skills": [
                        {"source": "github.com/a/b", "version": "v1", "names": ["alpha", "beta"]}
                    ],
                }
            ]
        )

        assert [s.skill_name for s in phase.skills] == ["alpha", "beta"]
        assert all(s.source_url.endswith("a/b") for s in phase.skills)

    def test_the_shorthand_form_still_yields_one(self) -> None:
        """The negative control: expansion must not multiply an ordinary
        entry."""
        (phase,) = _build_phase_defs(
            [
                {
                    "phase_id": "r",
                    "name": "R",
                    "order": 1,
                    "skills": ["owner/repo/one-skill@v1"],
                }
            ]
        )

        assert [s.skill_name for s in phase.skills] == ["one-skill"]
