"""Exported YAML must mean the same workflow when parsed back (#1015).

`_yaml_phase_lines` emitted 6 of 18 phase fields, so export then reinstall
produced a *different* workflow rather than an incomplete one: no per-phase
tool scoping, no provider (a codex review phase came back as claude), no
timeouts, no skills, no plugins, no delegation. All silent, all reporting
success.

This is the third layer of the same defect -- #1011 dropped fields on create,
#1013 dropped them on read, and this drops them on the way out. Export is the
path a workflow travels between machines, so it is the one where a silent
difference does the most damage.

THE TESTS PARSE WHAT WAS WRITTEN. Asserting on the emitted string would pass
while the YAML parses to something else, and that is precisely the failure
mode: the output is valid YAML that means the wrong thing. #1012 also shipped
a structural guard a decoy assignment satisfied, so a text-level check is not
enough here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from syn_api.routes.workflows.queries import _yaml_phase_lines
from syn_api.types import PhaseDefinitionResponse, PhaseRefResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit


def _phase() -> PhaseDefinitionResponse:
    """A phase declaring everything a reader or reinstaller needs."""
    return PhaseDefinitionResponse(
        phase_id="review",
        name="Review",
        order=3,
        execution_type="parallel",
        description="cross-model review",
        prompt_template="body",
        timeout_seconds=2400,
        allowed_tools=["Read", "Grep"],
        argument_hint="[task]",
        model="gpt-5.6-sol",
        provider="codex",
        allow_delegation=True,
        max_tokens=1234,
        input_artifact_types=["markdown"],
        output_artifact_types=["markdown"],
        claude_plugins=[
            PhaseRefResponse(source_url="https://github.com/foo/bar", name="bar", version="v1")
        ],
        skills=[PhaseRefResponse(source_url="https://github.com/a/b", name="alpha", version="v2")],
    )


def _parsed() -> Mapping[str, object]:
    """Emit one phase and parse it back through a real YAML loader.

    The round trip is the assertion. A string check would pass on output that
    parses to something else entirely, which is the whole failure mode.
    """
    document = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(_phase())))
    (phase,) = document["phases"]
    assert isinstance(phase, dict)
    return phase


class TestTheExportedPhaseParsesBack:
    def test_the_agent_block_carries_provider_and_model(self) -> None:
        """A codex review phase reinstalled as claude is the concrete harm:
        the workflow reports success and quietly stops doing cross-model
        review."""
        agent = _parsed().get("agent")
        assert isinstance(agent, dict)
        assert agent["provider"] == "codex"
        assert agent["model"] == "gpt-5.6-sol"

    def test_delegation_survives(self) -> None:
        agent = _parsed().get("agent")
        assert isinstance(agent, dict)
        assert agent["allow_delegation"] is True

    def test_tool_scoping_survives(self) -> None:
        """Without this, every claude phase reinstalls with the full toolset."""
        assert _parsed()["allowed_tools"] == ["Read", "Grep"]

    def test_timeout_survives(self) -> None:
        assert _parsed()["timeout_seconds"] == 2400

    def test_input_artifacts_survive(self) -> None:
        assert _parsed()["input_artifacts"] == ["markdown"]

    def test_argument_hint_survives(self) -> None:
        assert _parsed()["argument_hint"] == "[task]"

    def test_execution_type_survives_as_declared(self) -> None:
        """`parallel`, not the `sequential` default -- a value that could not
        have arrived by accident."""
        assert _parsed()["execution_type"] == "parallel"


class TestRefsAreExportedStructurally:
    """#1014 established that joining a ref into `source/name@version`
    corrupts it: a source already ending in the repo name reparses to a
    different repository. The export must not reintroduce that.
    """

    def test_a_skill_keeps_its_parts_separate(self) -> None:
        skills = _parsed().get("skills")
        assert isinstance(skills, list)
        entry = skills[0]
        assert isinstance(entry, dict)
        assert entry["source"] == "https://github.com/a/b"
        assert entry["names"] == ["alpha"]
        assert entry["version"] == "v2"

    def test_a_plugin_keeps_its_parts_separate(self) -> None:
        plugins = _parsed().get("claude_plugins")
        assert isinstance(plugins, list)
        entry = plugins[0]
        assert isinstance(entry, dict)
        assert entry["source"] == "https://github.com/foo/bar"
        assert entry["version"] == "v1"


class TestAnUndeclaredPhaseStaysUndeclared:
    """Export must not invent declarations a phase never made.

    Emitting `provider: null` or `allowed_tools: []` would turn "inherits the
    default" into "explicitly declares nothing", which reinstalls differently.
    """

    def test_nothing_optional_is_emitted_for_a_bare_phase(self) -> None:
        bare = PhaseDefinitionResponse(phase_id="p", name="P", order=1)
        document = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(bare)))
        (phase,) = document["phases"]

        for key in ("agent", "allowed_tools", "skills", "claude_plugins", "max_tokens"):
            assert key not in phase, f"{key} was invented for a phase that never declared it"

    def test_timeout_is_emitted_because_the_api_reports_one(self) -> None:
        """Not an exception carved out -- a real ambiguity, one layer up.

        `PhaseDefinitionResponse.timeout_seconds` defaults to 300 while the
        DOMAIN field defaults to None, so the API reports 300 for a phase that
        declared nothing and export cannot tell the two apart. Writing 300 is
        faithful to what the API says; suppressing it would make the export
        disagree with the GET a caller just read.

        The distinction is unrecoverable at this layer, which is the same
        declared-versus-defaulted problem #1013 hit with `allow_delegation`.
        Asserted here so the behaviour is a stated choice rather than an
        accident, and so a future change to that default fails loudly.
        """
        bare = PhaseDefinitionResponse(phase_id="p", name="P", order=1)
        document = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(bare)))
        (phase,) = document["phases"]

        assert (
            phase["timeout_seconds"]
            == PhaseDefinitionResponse.model_fields["timeout_seconds"].default
        )
