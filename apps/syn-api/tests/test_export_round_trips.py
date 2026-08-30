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
from syn_domain.contexts.orchestration._shared.workflow_definition import PhaseYamlDefinition

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
            PhaseRefResponse(
                source_url="https://github.com/foo/bar",
                name="custom-alias",
                version="v1",
                name_overridden=True,
            )
        ],
        skills=[
            PhaseRefResponse(
                source_url="https://github.com/a/b",
                name="alpha",
                version="v2",
                name_overridden=True,
            )
        ],
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
        # SINGULAR `name` for plugins. The plugin validator ignores `names`
        # entirely and derives the name from the source basename, so a plugin
        # exported with `names: [custom-alias]` reinstalls as `bar`. The alias
        # here differs from the basename deliberately -- the first version of
        # this test used `bar`, which is what the basename would produce
        # anyway, so it could not detect the wrong spelling.
        assert entry["name"] == "custom-alias"


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


class TestTheLoaderAcceptsWhatWeEmit:
    """The consumer, not the parser.

    The tests above parse the emitted YAML with `yaml.safe_load` and assert on
    the mapping. That proves it is well-formed YAML; it does NOT prove the
    workflow loader accepts it. Those are different questions, and the gap
    between them is where this PR's own defect lived: emitting `max_tokens`
    produced valid YAML that `PhaseYamlDefinition` REJECTS, so the export made
    packages uninstallable -- strictly worse than the lossy export it replaced.

    This is the same mistake as ticks 30-35, one level further out again: I
    tested the format and not the thing that consumes the format.
    """

    def _validate(self, phase: PhaseDefinitionResponse) -> PhaseYamlDefinition:
        emitted = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0]
        # The loader wants the prompt inline; export writes it to a sibling
        # file, so substitute exactly what the installer would have resolved.
        emitted.pop("prompt_file", None)
        emitted["prompt_template"] = "body"
        return PhaseYamlDefinition.model_validate(emitted)

    def test_a_fully_declared_phase_validates(self) -> None:
        """The whole point: exported YAML must reinstall."""
        assert self._validate(_phase()) is not None

    def test_a_bare_phase_validates(self) -> None:
        assert self._validate(PhaseDefinitionResponse(phase_id="p", name="P", order=1)) is not None

    def test_max_tokens_does_not_make_the_package_uninstallable(self) -> None:
        """`max_tokens` is deliberately not in the authoring schema.

        A phase can only carry one via the untyped JSON create path, which
        YAML refuses -- so emitting it exported a package that could never be
        installed. Not part of the schema means not exported."""
        assert (
            self._validate(
                PhaseDefinitionResponse(phase_id="p", name="P", order=1, max_tokens=1234)
            )
            is not None
        )


class TestValuesCannotRestructureTheDocument:
    """Every interpolated scalar is quoted.

    Hand-built YAML with unquoted interpolation lets a value change the
    document's meaning rather than its content: a comma splits one name into
    two, a colon-space breaks the mapping, `null`/`true`/`123` parse as other
    types, and a leading `*` or `&` is an alias or anchor.
    """

    def _phase_with(self, **kwargs: object) -> Mapping[str, object]:
        phase = PhaseDefinitionResponse(phase_id="p", name="P", order=1, **kwargs)  # type: ignore[arg-type]
        return yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0]

    def test_a_model_named_null_stays_a_string(self) -> None:
        """Unquoted, `model: null` erases the model instead of naming it."""
        agent = self._phase_with(provider="claude", model="null").get("agent")
        assert isinstance(agent, dict)
        assert agent["model"] == "null"

    def test_a_numeric_version_stays_a_string(self) -> None:
        refs = [PhaseRefResponse(source_url="https://github.com/a/b", version="123")]
        skills = self._phase_with(skills=refs)["skills"]
        assert isinstance(skills, list)
        assert skills[0]["version"] == "123"

    def test_a_version_with_a_colon_does_not_break_the_document(self) -> None:
        refs = [PhaseRefResponse(source_url="https://github.com/a/b", version="release: candidate")]
        skills = self._phase_with(skills=refs)["skills"]
        assert isinstance(skills, list)
        assert skills[0]["version"] == "release: candidate"

    def test_a_name_containing_a_comma_stays_one_name(self) -> None:
        """Unquoted in a flow list, a comma silently becomes two entries."""
        refs = [
            PhaseRefResponse(
                source_url="https://github.com/a/b", name="alpha,beta", name_overridden=True
            )
        ]
        skills = self._phase_with(skills=refs)["skills"]
        assert isinstance(skills, list)
        assert skills[0]["names"] == ["alpha,beta"]

    def test_a_source_with_a_hash_is_not_truncated(self) -> None:
        """Unquoted, `# ` starts a comment and eats the rest of the line."""
        refs = [PhaseRefResponse(source_url="https://github.com/a/b #frag")]
        skills = self._phase_with(skills=refs)["skills"]
        assert isinstance(skills, list)
        assert skills[0]["source"] == "https://github.com/a/b #frag"


class TestAShorthandRefExportsAsAScalar:
    """A ref known only as a shorthand string has no source/version to split.

    Emitting `- source: owner/repo@v1` with no `version` produced a mapping
    BOTH reference models reject, so the package would not reinstall.
    """

    def test_it_is_emitted_as_a_bare_entry(self) -> None:
        phase = PhaseDefinitionResponse(
            phase_id="p", name="P", order=1, skills=[PhaseRefResponse(raw="owner/repo/s@v1")]
        )
        skills = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0][
            "skills"
        ]
        assert skills == ["owner/repo/s@v1"]

    def test_a_ref_naming_nothing_is_not_exported(self) -> None:
        """`source: null` would export a reference that cannot resolve."""
        phase = PhaseDefinitionResponse(
            phase_id="p", name="P", order=1, skills=[PhaseRefResponse()]
        )
        parsed = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0]
        assert "skills" not in parsed


class TestProvenanceIsNotInvented:
    """A derived name must not be exported as an authored one.

    The loader sets `name_overridden=True` whenever a name is present, so
    emitting a name that was DERIVED from the source basename makes the
    reinstalled phase claim the author chose it. When it was not overridden
    the loader derives the same name from the source anyway, so emitting it
    adds nothing and changes provenance.
    """

    def _skills(self, ref: PhaseRefResponse) -> object:
        phase = PhaseDefinitionResponse(phase_id="p", name="P", order=1, skills=[ref])
        return yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0][
            "skills"
        ][0]

    def test_a_derived_name_is_not_emitted(self) -> None:
        entry = self._skills(
            PhaseRefResponse(source_url="https://github.com/a/b", name="b", name_overridden=False)
        )
        assert isinstance(entry, dict)
        assert "names" not in entry

    def test_an_authored_name_is_emitted(self) -> None:
        entry = self._skills(
            PhaseRefResponse(
                source_url="https://github.com/a/b", name="chosen", name_overridden=True
            )
        )
        assert isinstance(entry, dict)
        assert entry["names"] == ["chosen"]


class TestListValuesCannotSplit:
    """Per-item quoting is not enough; the surrounding flow list matters.

    `a,b` reads back as `a,b` on its own, so a per-value quoting decision says
    "safe" -- and inside `[a,b]` it becomes two entries. The emitter builds
    the whole list instead.
    """

    def _phase(self, **kw: object) -> Mapping[str, object]:
        p = PhaseDefinitionResponse(phase_id="p", name="P", order=1, **kw)  # type: ignore[arg-type]
        return yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(p)))["phases"][0]

    def test_an_output_artifact_with_a_comma_stays_one_entry(self) -> None:
        assert self._phase(output_artifact_types=["a,b"])["output_artifacts"] == ["a,b"]

    def test_a_tool_with_a_comma_stays_one_entry(self) -> None:
        assert self._phase(allowed_tools=["Read", "x,y"])["allowed_tools"] == ["Read", "x,y"]

    def test_an_artifact_named_null_stays_a_string(self) -> None:
        """Unquoted, `[null]` reinstalls as `[None]` and the loader rejects it."""
        assert self._phase(output_artifact_types=["null"])["output_artifacts"] == ["null"]


class TestMultilineValuesSurvive:
    """A hand-written double-quoted scalar keeps PHYSICAL newlines, and YAML
    folds those to a single space -- so `A\nB` reinstalled as `A B`."""

    def test_a_multiline_description_round_trips(self) -> None:
        phase = PhaseDefinitionResponse(phase_id="p", name="P", order=1, description="A\nB")
        parsed = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0]
        assert parsed["description"] == "A\nB"
