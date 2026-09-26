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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from pydantic import ValidationError

from syn_api.routes.workflows.queries import _yaml_phase_lines
from syn_api.types import PhaseDefinitionResponse, PhaseRefResponse, WorkflowDetail
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


def _valid_phase() -> PhaseDefinitionResponse:
    """Everything a reader needs, and VALID under the current schema.

    Separate from `_phase()` on purpose. `_phase()` carries deliberately
    refused declarations so the round trip can be shown to preserve them; this
    one is what an installable package looks like.
    """
    return _phase().model_copy(
        update={
            "execution_type": "sequential",
            "provider": "claude",
            "model": "sonnet",
            "max_tokens": None,
        }
    )


def _valid_workflow_detail() -> WorkflowDetail:
    """Two phases, because one cannot satisfy an input_artifacts declaration.

    The producer emits `markdown` and the consumer declares it, so the exported
    package also demonstrates that the cross-phase validator accepts a real
    workflow rather than only rejecting broken ones.
    """
    producer = _valid_phase().model_copy(
        update={
            "phase_id": "research",
            "name": "Research",
            "order": 1,
            "input_artifact_types": [],
            "output_artifact_types": ["markdown"],
        }
    )
    return WorkflowDetail(
        id="wf-1",
        name="Round Trip",
        workflow_type="research",
        classification="standard",
        phases=[producer, _valid_phase()],
        requires_repos=False,
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
        """Display metadata, and it must round-trip like any other field.

        Briefly removed during #1039 on the assumption it was inert; it is not
        - the dashboard renders it - so dropping it from the export would have
        silently stripped the hint from every reinstalled workflow.
        """
        assert _parsed()["argument_hint"] == "[task]"

    def test_execution_type_survives_as_declared(self) -> None:
        """`parallel`, not the `sequential` default - a value that could not
        have arrived by accident.

        Preserved DELIBERATELY even though the loader now refuses it (#1039).
        Dropping it would launder the phase: a stored `human_in_loop` template
        that this platform refuses would reinstall as `sequential` and then
        run, with the human gate its author believed in silently gone. See
        TestARefusedDeclarationDoesNotLaunder.
        """
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

    def test_a_fully_declared_VALID_phase_validates(self) -> None:
        """The whole point: exported YAML must reinstall.

        The phase must be VALID under the current schema. The shared `_phase()`
        fixture is deliberately not: it carries `execution_type: parallel` and
        codex-plus-tools, both of which the loader now refuses. Export
        preserves those faithfully, so the refusal survives the round trip -
        see TestARefusedDeclarationDoesNotLaunder. Asserting installability
        against an invalid fixture would force export to launder it.
        """
        assert self._validate(_valid_phase()) is not None

    def test_the_exported_MANIFEST_reinstalls_not_just_the_yaml(self) -> None:
        """Load the real files, through the real loader (#1039).

        `_validate` above pops `prompt_file` and substitutes the prompt inline,
        so it never reads the exported `phases/<id>.md`. That blind spot hid a
        live defect: `_build_phase_md` emitted `allowed-tools` for a codex
        phase while the YAML emitter filtered it out, so the two halves of one
        package disagreed and the package could not be installed. Only a test
        that writes the manifest and loads it back can see that.
        """
        import tempfile

        from syn_api.routes.workflows.queries import _build_package_files
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        detail = _valid_workflow_detail()
        files: dict[str, str] = {}
        _build_package_files(detail, files)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for rel, content in files.items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            loaded = WorkflowDefinition.from_file(root / "workflow.yaml")

        assert [p.id for p in loaded.phases] == [p.phase_id for p in detail.phases]
        assert loaded.phases[1].allowed_tools == ["Read", "Grep"]
        assert loaded.phases[1].input_artifacts == ["markdown"]

        # THE TWO EMITTERS MUST AGREE. Asserting the loaded value alone does
        # NOT test the frontmatter: workflow.yaml carries `allowed_tools` too
        # and wins the merge, so a markdown emitter that dropped or added a key
        # would be invisible. Verified by mutation - deleting the frontmatter
        # line left this test green until it compared the two halves directly.
        frontmatter = yaml.safe_load(files["phases/review.md"].split("---")[1])

        assert frontmatter["allowed-tools"] == ",".join(_valid_phase().allowed_tools)
        assert frontmatter["model"] == _valid_phase().model

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


class TestAPhaseIdIsValidatedWhole:
    """#1355's defect at the export hop.

    `_validate_phase_id` exists to keep an id safe to interpolate into a path
    and into hand-built YAML, and it is the LAST thing between a phase id and
    both. It asked an anchored `^...$` pattern with `.match()`, which in Python
    stops at a trailing newline rather than at the end of the string, so
    `premise\n` passed the safety check and was written into two lines of the
    emitted document.

    Tested at the emitter, not at the pattern: the value was always well-formed
    where it was checked and only became wrong where it was used.
    """

    def test_a_phase_id_with_a_trailing_newline_is_refused(self) -> None:
        phase = PhaseDefinitionResponse(phase_id="premise\n", name="P", order=1)

        with pytest.raises(ValueError, match="unsafe characters"):
            _yaml_phase_lines(phase)

    def test_a_dotted_phase_id_still_exports(self) -> None:
        """The negative control. `.` is legal in the grammar, so tightening the
        matcher must not start refusing ids that were always valid."""
        phase = PhaseDefinitionResponse(phase_id="premise.v2", name="P", order=1)

        parsed = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0]

        assert parsed["id"] == "premise.v2"
        assert parsed["prompt_file"] == "phases/premise.v2.md"


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


class TestARefusedDeclarationDoesNotLaunder:
    """Export must not turn a template this platform refuses into one it runs.

    The safety-critical case is `human_in_loop`. Its author believes a human
    approves the phase before it runs. Nothing implements that, so the loader
    refuses it. If export DROPPED the field, the phase would reinstall as
    `sequential` - accepted, runnable, and silently unattended. The refusal
    would have been laundered away by a round trip.

    So export preserves the declaration and the reinstall refuses. An
    uninstallable package names the problem; a laundered one hides it.
    """

    def _reinstall(self, phase: PhaseDefinitionResponse) -> None:
        emitted = yaml.safe_load("phases:\n" + "\n".join(_yaml_phase_lines(phase)))["phases"][0]
        emitted.pop("prompt_file", None)
        emitted["prompt_template"] = "body"
        PhaseYamlDefinition.model_validate(emitted)

    @pytest.mark.parametrize("declared", ["human_in_loop", "parallel"])
    def test_an_unimplemented_execution_type_still_refuses_after_a_round_trip(
        self, declared: str
    ) -> None:
        phase = PhaseDefinitionResponse(phase_id="p", name="P", order=1, execution_type=declared)

        with pytest.raises(ValidationError, match="not implemented"):
            self._reinstall(phase)

    def test_codex_with_tools_still_refuses_after_a_round_trip(self) -> None:
        phase = PhaseDefinitionResponse(
            phase_id="p",
            name="P",
            order=1,
            provider="codex",
            allowed_tools=["Read", "Grep"],
        )

        with pytest.raises(ValidationError, match="cannot honour allowed_tools"):
            self._reinstall(phase)


# ---------------------------------------------------------------------------
# #1429: the four fields the comment claimed were not dropped
# ---------------------------------------------------------------------------
#
# `can_open_pr` decides the GitHub token's permission level. A dropped
# declaration reinstalls the phase with `pull_requests: read`, so it pushes a
# branch and then fails at `gh pr create` - which reads as a GitHub App
# misconfiguration, not a lost YAML field. That cost a multi-hour
# investigation into app permissions, installation repo selection and app
# identity, all of which were correct.
#
# The inverse direction matters just as much and is easier to get wrong.
# `clone_repos` and `delivers_repo_changes` default TRUE, so a truthy-only
# emit guard drops an explicit `false` and reinstalls it as `true`. The phase
# then clones repos it declared it did not want, or has the unpushed-work gate
# treat a build artifact as a lost deliverable. Same laundering, opposite sign,
# which is why these tests assert BOTH directions per field.


@dataclass(frozen=True)
class _ExportedPhase:
    """What one exported phase says, read back off the parsed YAML.

    A typed view rather than the raw mapping. `None` means the key was ABSENT,
    which is the distinction every test here turns on: absent means "inherits
    the loader default", present means "explicitly declares". A bare dict makes
    those two look the same at the call site.
    """

    phase_id: str
    name: str
    order: int
    prompt_file: str
    top_level_keys: frozenset[str]
    agent_keys: frozenset[str]
    can_open_pr: bool | None
    clone_repos: bool | None
    delivers_repo_changes: bool | None
    agent_sandbox: str | None
    has_agent_block: bool

    def declares(self, key: str) -> bool:
        """Whether the exported YAML carries `key` at the phase's top level."""
        return key in self.top_level_keys


def _parsed_phase(phase: PhaseDefinitionResponse) -> _ExportedPhase:
    """Export one phase and parse the YAML back, as this file's header requires."""
    text = "\n".join(["phases:", *_yaml_phase_lines(phase)])
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, dict)
    phases = parsed["phases"]
    assert isinstance(phases, list) and len(phases) == 1
    entry = phases[0]
    assert isinstance(entry, dict)
    agent = entry.get("agent")
    agent_map = agent if isinstance(agent, dict) else {}
    sandbox = agent_map.get("sandbox")
    return _ExportedPhase(
        phase_id=str(entry["id"]),
        name=str(entry["name"]),
        order=int(entry["order"]),
        prompt_file=str(entry["prompt_file"]),
        top_level_keys=frozenset(str(k) for k in entry),
        agent_keys=frozenset(str(k) for k in agent_map),
        can_open_pr=entry.get("can_open_pr"),
        clone_repos=entry.get("clone_repos"),
        delivers_repo_changes=entry.get("delivers_repo_changes"),
        agent_sandbox=None if sandbox is None else str(sandbox),
        has_agent_block=isinstance(agent, dict),
    )


class TestCanOpenPrSurvivesExport:
    def test_true_is_emitted(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"can_open_pr": True}))
        assert entry.can_open_pr is True

    def test_false_is_the_default_and_stays_absent(self) -> None:
        """Absent means False to the loader, so emitting it would add noise."""
        entry = _parsed_phase(_valid_phase().model_copy(update={"can_open_pr": False}))
        assert not entry.declares("can_open_pr")
        assert (
            PhaseYamlDefinition(id="x", name="x", order=1, prompt_file="x.md").can_open_pr is False
        )

    def test_the_loader_reads_back_what_export_wrote(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"can_open_pr": True}))
        loaded = PhaseYamlDefinition(
            id=entry.phase_id,
            name=entry.name,
            order=entry.order,
            prompt_file=entry.prompt_file,
            can_open_pr=bool(entry.can_open_pr),
        )
        assert loaded.can_open_pr is True, (
            "export wrote can_open_pr but the loader did not read it back as True; "
            "a publishing phase would reinstall unable to publish"
        )


class TestDefaultTrueFieldsSurviveExport:
    """The direction a truthy-only emit guard silently reverses."""

    def test_clone_repos_false_is_emitted(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"clone_repos": False}))
        assert entry.clone_repos is False, (
            "an explicit clone_repos: false was dropped, so the phase reinstalls "
            "cloning repos its author declared it did not need"
        )

    def test_clone_repos_true_stays_absent(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"clone_repos": True}))
        assert not entry.declares("clone_repos")

    def test_delivers_repo_changes_false_is_emitted(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"delivers_repo_changes": False}))
        assert entry.delivers_repo_changes is False, (
            "an explicit delivers_repo_changes: false was dropped, so the "
            "unpushed-work gate reinstalls treating build output as a lost deliverable"
        )

    def test_delivers_repo_changes_true_stays_absent(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"delivers_repo_changes": True}))
        assert not entry.declares("delivers_repo_changes")


class TestSandboxSurvivesExport:
    """`sandbox` is an `agent.` field in the authoring schema, not top level."""

    def test_non_default_sandbox_is_emitted_under_agent(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"sandbox": "read-only"}))
        assert entry.has_agent_block
        assert entry.agent_sandbox == "read-only", (
            "a read-only verify phase reinstalls at the default full-access level, "
            "so the verifier regains write access to what it certifies"
        )

    def test_it_is_not_emitted_at_the_top_level(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"sandbox": "read-only"}))
        assert not entry.declares("sandbox"), (
            "sandbox at the top level is not in the authoring schema; the loader "
            "would ignore it and the phase would reinstall at the default"
        )

    def test_the_default_stays_absent(self) -> None:
        from syn_shared.agents import DEFAULT_PHASE_SANDBOX

        entry = _parsed_phase(_valid_phase().model_copy(update={"sandbox": DEFAULT_PHASE_SANDBOX}))
        assert entry.agent_sandbox is None


class TestTheSchemaClaimIsChecked:
    """Replaces a comment that asserted this and was wrong for four fields.

    `_yaml_phase_lines` carried the line "Nothing that CAN be expressed is
    dropped here". It was false for can_open_pr, clone_repos,
    delivers_repo_changes and agent.sandbox.

    THE FIRST VERSION OF THIS TEST WAS A DECOY, and a codex review said so.
    It asserted the schema had phase properties, that the response model had
    fields, and that the two sets overlapped. All three can hold while the
    export drops every field, because none of them looks at the export. It
    replaced a false comment with a check that could not fail for the reason
    the comment was false.

    This version round-trips each field through the emitter and the loader.
    """

    @staticmethod
    def _schema_phase_properties() -> frozenset[str]:
        schema_path = (
            Path(__file__).resolve().parents[3] / "schemas" / "plugin" / "workflow.schema.json"
        )
        if not schema_path.is_file():
            pytest.fail(f"authoring schema not found at {schema_path}")
        import json

        schema = json.loads(schema_path.read_text())
        defs = schema.get("$defs") or schema.get("definitions") or {}
        phase_def = defs.get("PhaseYamlDefinition") or {}
        props = phase_def.get("properties") or {}
        if not props:
            pytest.fail(
                "could not locate PhaseYamlDefinition properties in the authoring "
                "schema; this test must not pass on an empty set"
            )
        return frozenset(str(name) for name in props)

    def test_the_four_fields_are_expressible_in_the_schema(self) -> None:
        """Where each field lives. `sandbox` is under `agent`, not top level."""
        props = self._schema_phase_properties()
        for name in ("can_open_pr", "clone_repos", "delivers_repo_changes"):
            assert name in props, f"{name} is not a top-level phase property in the schema"
        assert "sandbox" not in props, (
            "sandbox became a top-level phase property; the export emits it under "
            "`agent:` and would now be writing it to the wrong place"
        )

    def test_each_field_round_trips_through_the_loader(self) -> None:
        """The assertion the decoy version was missing.

        Export a phase carrying a NON-DEFAULT value for each field, parse the
        YAML, load it through PhaseYamlDefinition, and compare against what
        was exported. This is what "nothing expressible is dropped" means.
        """
        phase = _valid_phase().model_copy(
            update={
                "can_open_pr": True,
                "clone_repos": False,
                "delivers_repo_changes": False,
                "sandbox": "read-only",
            }
        )
        entry = _parsed_phase(phase)

        assert entry.has_agent_block, "the agent block vanished, so sandbox cannot survive"

        loaded = PhaseYamlDefinition(
            id=entry.phase_id,
            name=entry.name,
            order=entry.order,
            prompt_file=entry.prompt_file,
            can_open_pr=bool(entry.can_open_pr),
            clone_repos=bool(entry.clone_repos),
            delivers_repo_changes=bool(entry.delivers_repo_changes),
        )
        assert loaded.can_open_pr is True
        assert loaded.clone_repos is False
        assert loaded.delivers_repo_changes is False
        assert entry.agent_sandbox == "read-only"

    def test_the_read_model_stores_them(self) -> None:
        """The third seam: to_dict is what is actually stored and served.

        Found by codex review. The projection built a phase carrying these,
        stored `to_dict()` without them, and `get_by_id` reloaded the defaults
        - so the API reported a publishing phase as can_open_pr: false and a
        read-only phase as full-access. Export then wrote the wrong phase from
        correct-looking in-memory state.
        """
        from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
            PhaseDefinitionDetail,
            WorkflowDetail,
        )

        detail = WorkflowDetail(
            id="wf",
            name="wf",
            workflow_type="research",
            classification="simple",
            description="round-trip probe",
            phases=[
                PhaseDefinitionDetail(
                    id="review",
                    name="Review",
                    order=1,
                    can_open_pr=True,
                    clone_repos=False,
                    delivers_repo_changes=False,
                    sandbox="read-only",
                )
            ],
        )
        stored = detail.to_dict()
        phase = stored["phases"][0]
        for key, want in (
            ("can_open_pr", True),
            ("clone_repos", False),
            ("delivers_repo_changes", False),
            ("sandbox", "read-only"),
        ):
            assert key in phase, (
                f"to_dict dropped {key}; the read model carries it but the STORED shape "
                f"does not, so every reader gets the default"
            )
            assert phase[key] == want

        reloaded = WorkflowDetail.from_dict(stored).phases[0]
        assert reloaded.can_open_pr is True
        assert reloaded.clone_repos is False
        assert reloaded.delivers_repo_changes is False
        assert reloaded.sandbox == "read-only", (
            "a read-only phase reloaded at a different sandbox level; a security field "
            "must never read back LESS restricted than it was stored"
        )


@pytest.mark.unit
class TestAnInvalidSandboxIsNotLaundered:
    """An invalid stored value must not export as a valid, MORE permissive one.

    Found by codex review. The guard was `if phase.sandbox`, so `""` was
    omitted and the phase reinstalled at the default full-access. The API
    create path can store that value and execution preserves it in order to
    reject it; export was the one step that made it look fine.

    Same reasoning this file already applies to a refused `execution_type`:
    an uninstallable package names the problem, a silently corrected one does
    not.
    """

    def test_an_empty_sandbox_is_still_emitted(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"sandbox": ""}))
        assert entry.has_agent_block
        assert entry.agent_sandbox is not None, (
            "an invalid empty sandbox was dropped, so the phase reinstalls at "
            "full-access - export upgraded its privileges"
        )
        assert entry.agent_sandbox == ""

    def test_a_bogus_sandbox_is_still_emitted(self) -> None:
        entry = _parsed_phase(_valid_phase().model_copy(update={"sandbox": "not-a-level"}))
        assert entry.has_agent_block
        assert entry.agent_sandbox == "not-a-level"

    def test_the_default_is_still_omitted(self) -> None:
        """Widening the guard must not start writing the default back."""
        from syn_shared.agents import DEFAULT_PHASE_SANDBOX

        entry = _parsed_phase(_valid_phase().model_copy(update={"sandbox": DEFAULT_PHASE_SANDBOX}))
        assert entry.agent_sandbox is None
