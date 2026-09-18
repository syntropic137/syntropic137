"""Validate every workflow YAML in the repo against WorkflowDefinition.

The schema pipeline was already 90% built: WorkflowDefinition is the source of
truth, `export_plugin_schemas.py` generates workflow.schema.json from it, and
`check-plugin-schemas` fails if the two drift. What nobody did was run the
repo's own workflow FILES through it.

So a workflow could declare a shape the platform rejects and reach the
dashboard, where the field renders and can never be submitted (#942). The
schema was right the whole time; nothing pointed it at the workflows.

It also checks something the API does NOT: that a phase's prompt and its tool
grant agree. That is a coherence property of the pair, not a validity property
of either half, so no schema can express it and the create endpoint accepts a
workflow that has it wrong. See `grant_violations`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PhaseYamlDefinition,
    WorkflowDefinition,
    is_phase_id,
)
from syn_domain.contexts.orchestration._shared.yaml_to_command import build_command_from_definition

if TYPE_CHECKING:
    from collections.abc import Callable

_ROOT = Path(__file__).resolve().parent.parent
_ROOTS = ("workflows",)


def _is_package_member(path: Path) -> bool:
    """True when this file belongs to a workflow PACKAGE rather than standing alone.

    A package carries a plugin manifest at its root; its workflow files may use
    package-relative skill references that only resolve in that context.
    """
    for parent in path.parents:
        if parent == _ROOT:
            break
        if any(
            (parent / n).exists()
            for n in ("syntropic137-plugin.json", "syntropic137.yaml", "marketplace.json")
        ):
            return True
    return False


def _workflow_files() -> list[Path]:
    found: list[Path] = []
    for root in _ROOTS:
        base = _ROOT / root
        if base.exists():
            found.extend(sorted(p for p in base.rglob("*.yaml") if p.is_file()))
    return found


def validate_file(path: Path) -> str | None:
    """Validate ONE workflow file to the depth the create endpoint uses.

    Returns the failure reason, or None when the file is acceptable.

    Extracted so tests can drive the real thing. The first version of the test
    file reimplemented this logic, so reverting the gate to a shallow
    `model_validate` left every test green - a test suite measuring its own
    copy of the code rather than the code.
    """
    try:
        # from_file, NOT model_validate(raw): the parse model accepts a
        # `prompt_file` that does not exist, and the API's create endpoint
        # then rejects it at conversion with HTTP 400. A gate that stops at
        # the parse model passes definitions the platform refuses, which is
        # the exact class it exists to catch.
        definition = WorkflowDefinition.from_file(path)
        # Then the SAME conversion the create endpoint runs. Loading is not
        # validation: an unresolved prompt_file is rejected here, not above.
        build_command_from_definition(definition)
    # OSError too: `from_file` raises FileNotFoundError for an unresolved
    # prompt_file, and letting that escape crashes the gate with a traceback
    # instead of naming the file and the reason.
    except (ValidationError, ValueError, OSError) as exc:
        return str(exc)
    return None


#: Info strings that mean a fenced block is data being SHOWN, not run.
#:
#: This list is inverted on purpose, and the inversion is the whole design.
#: The first version listed the SHELL tags - `bash|sh|shell|zsh|console`,
#: three backticks, case-sensitive - so every other spelling CommonMark
#: allows silently missed: a bare fence, `Bash`, four backticks, a tilde
#: fence. A miss produced no violation, and no violation reads as a pass, so
#: the gate could not distinguish "runs no shell" from "runs shell in a
#: spelling I cannot read" (#1261). Bare fences outnumber tagged ones in this
#: repo's own prompts, which made the common spelling the invisible one.
#:
#: Listing the exemptions instead moves the cost of an unanticipated spelling
#: from a false negative nobody observes to a false positive someone tags.
#:
#: THE BAR FOR ADDING ONE: the tag must denote content that cannot be a shell
#: instruction under any reading - a data or markup format, shown rather than
#: run. These five meet it and are what this repo's prompts already use to
#: display structure. A programming language does NOT meet it: a prompt
#: fencing a `python` block is usually telling the phase to run that script,
#: and exempting it would reopen exactly this defect for that spelling. When
#: in doubt leave it out; the failure is visible and the fix is one word.
_NON_SHELL_INFO = frozenset({"text", "yaml", "json", "markdown", "diff"})

#: A fence line: CommonMark's two characters, three or more of them, behind
#: whatever CONTAINERS the prompt indents it inside. Capturing the run and the
#: info string separately is what lets the walk below pair openers with
#: closers instead of scanning lines - a closer, alone on its line, is
#: indistinguishable from a bare opener, so a line scanner treating bare as
#: shell would report every exempt block via its own closing fence.
#:
#: The container prefix is the second place a fence can be missed, and it was
#: missed the same way as the first. The info-string layer was fixed to read
#: every SPELLING - bare, capitalised, tilde, four-backtick - while this
#: pattern still admitted only whitespace and one list marker. A fence inside
#: a block quote therefore matched nothing, and a miss reads as a pass. A
#: quoted command is not an unusual way to write a prompt; it is how a prompt
#: shows the step it wants run.
#:
#: The prefix takes ANY sequence of container markers, in any order and to any
#: depth. An earlier version allowed quote markers followed by at most one list
#: marker, which encoded one fixed nesting order as if it were the rule.
#: CommonMark imposes no such order, so `- > ```bash` and `- - ```bash` -
#: both valid, both instructions to run something - matched nothing and passed.
#: An unterminated fence makes that miss silent, since there is no later
#: closing line whose mismatch might expose it.
_CONTAINER = r"(?:[ \t]*(?:>|[-*+][ \t]|\d+\.[ \t]))*"
_FENCE = re.compile(rf"^({_CONTAINER}[ \t]*)(`{{3,}}|~{{3,}})(.*)", re.M)


def _quote_depth(prefix: str) -> int:
    """How many block-quote containers a fence line sits inside.

    The pairing walk needs this because a block quote ENDS when its prefix
    stops. An exempt opener inside a quote does not get to swallow the rest of
    the document: once a fence appears at a shallower depth, the container that
    held the opener is over, and the opener is over with it. Without that the
    widening below would have been a fail-open, since a quoted ```text could
    absorb an unquoted ```bash that follows it.
    """
    return prefix.count(">")


def _language(info: str) -> str:
    """The language an info string names, or "" when it names none.

    CommonMark takes the language to be the info string's first word, so
    `bash title="x"` is bash. Lowercased because `Bash` names the same thing
    and case-sensitivity was the second of the four misses.
    """
    words = info.split()
    return words[0].lower() if words else ""


def _first_shell_fence(prompt: str) -> int | None:
    """Offset of the first fenced block this prompt tells the phase to RUN.

    Deliberately the fence and not a vocabulary of commands. A list of
    interesting binaries is a special case per binary, always one short, and
    whichever one it is missing is the one the next prompt uses. A fence says
    "run this" in the prompt's own syntax and needs no such list.

    Returns None only when every fenced block carried an exempt info string -
    never merely because a fence was written in an unfamiliar way.
    """
    opener: str | None = None
    opener_depth = 0
    for match in _FENCE.finditer(prompt):
        prefix, marker, info = match.group(1), match.group(2), match.group(3).strip()
        depth = _quote_depth(prefix)
        if opener is not None and depth < opener_depth:
            # The opener's block quote ENDED. CommonMark closes a container
            # when its prefix stops, and an unterminated fence inside it closes
            # with the container. Without this the exempt opener stays open
            # forever and absorbs every fence that follows, which is how a
            # quoted `text` block came to swallow a real ```bash instruction.
            opener = None
            opener_depth = 0

        if opener is None:
            if _language(info) not in _NON_SHELL_INFO:
                return match.start()
            opener = marker
            opener_depth = depth
        elif (
            depth == opener_depth
            and marker[0] == opener[0]
            and len(marker) >= len(opener)
            and not info
        ):
            # CommonMark's closing rule: same container depth, same character,
            # at least as long, and no info string.
            #
            # The depth term is load bearing, and the argument that it was not
            # ("a deeper fence can only end a block EARLY, which fails closed")
            # is wrong: it stops at the one fence and ignores that the walk
            # DESYNCS afterwards. Given a ```text block displaying a `> ```
            # line, a depth-blind closer ends the exempt block there, reads the
            # displayed `~~~text` line after it as a new exempt opener, and
            # then cannot close that phantom with backticks - so a real ```bash
            # fence further down is absorbed as content and the phase passes.
            # It is also a false positive in its own right: the real closing
            # fence of such a block gets reported as a shell instruction.
            #
            # Anything between a matched pair is content: a `text` block
            # quoting a ```bash fence is showing it, not running it, and the
            # report template does exactly that.
            opener = None
    return None


def _told_to_run_shell(phase: PhaseYamlDefinition) -> str | None:
    # from_file has already inlined prompt_file into prompt_template, so this
    # is the phase's own instructions however they were written - one file or
    # two. It is NOT the whole prompt the agent receives: `_build_prompt` in
    # the API prepends the platform preamble, which carries its own ```bash
    # block to every phase regardless of grant. Checking the rendered prompt
    # would therefore report every phase in the repo, so the phase's own text
    # is both what this can see and what it should be judging.
    prompt = phase.prompt_template or ""
    start = _first_shell_fence(prompt)
    if start is None:
        return None
    return f"prompt line {prompt.count('\n', 0, start) + 1}"


def _required_to_produce_an_artifact(phase: PhaseYamlDefinition) -> str | None:
    # `output_artifacts` and not a phrase in the prompt. Every phase states its
    # deliverable twice - once in prose and once in this field - and only the
    # field is structured. Reading the prose instead would mean matching "write
    # to artifacts/output", which the phases that only READ that directory also
    # say, in the boilerplate that tells them where their input came from.
    if not phase.output_artifacts:
        return None
    return f"it declares output_artifacts {phase.output_artifacts}"


@dataclass(frozen=True)
class _Demand:
    """Something a phase is REQUIRED to be able to do, and what would let it.

    Each demand knows how to find itself in a phase, so a new capability is one
    entry in `_DEMANDS` rather than another branch in the loop below. Where the
    requirement is stated differs - the shell one is in the prompt, the artifact
    one is in the phase's own declarations - and that difference is this type's
    whole job to absorb: the caller asks "is this phase able to do what it must"
    and never learns which half of the file the answer came from.
    """

    #: Completes "phase X must ...", so phrase it as a verb.
    must: str
    #: Holding ANY of these satisfies the demand. More than one because there
    #: is usually more than one honest way: a phase with Bash can create a file
    #: with a heredoc and needs no Write to do it.
    satisfied_by: frozenset[str]
    #: Where the requirement is stated, or None when this phase has no such
    #: requirement.
    locate: Callable[[PhaseYamlDefinition], str | None]


_DEMANDS: tuple[_Demand, ...] = (
    _Demand(
        must="run shell",
        satisfied_by=frozenset({"Bash"}),
        locate=_told_to_run_shell,
    ),
    _Demand(
        must="create a file",
        satisfied_by=frozenset({"Bash", "Write"}),
        locate=_required_to_produce_an_artifact,
    ),
)


def grant_violations(path: Path) -> list[str]:
    """Phases in this file that must do something their tool grant forbids.

    THE INVARIANT: a phase's instructions and its tool grant must agree. Every
    phase told to do something must be able to do it; every phase that must not
    do something must not be told to.

    WHY A GATE AND NOT A REVIEW. #1110 added a `gh pr comment` step to the
    pr-review `report` prompt. `report` grants Read, Grep, Glob, Write - no
    Bash. The install succeeded, the deployed prompt carried the step, and
    three reviews (#1113, #1115, #1117) each wrote "this needs a tool this
    phase does not have" while their verdicts stayed in object storage (#1122).
    Nothing failed. Both halves were individually valid and only the pair was
    wrong, which is exactly the shape a human reviewer reads past: the prompt
    is in one file and the grant is in another.

    WHY IT CHECKS MORE THAN THE PROMPT. The first version of this gate knew
    only the shell fence, and #1122's own fix then missed three phases of
    `research-experiment-plan` that declare a markdown output while granting
    [Read, Grep, Glob] - no Write, no Bash, so nothing they produced could
    reach `artifacts/output/` and the phase after each of them reads an empty
    directory. Same defect, stated in the declaration rather than in a fence.
    A gate that knows one spelling of a defect certifies the others.

    An empty allowlist is not a restriction - `_build_agent_command` omits
    `--tools` entirely - so those phases hold every tool and cannot violate
    this. Codex phases are in that set by construction; the validator already
    refuses a tool list on them.
    """
    definition = WorkflowDefinition.from_file(path)
    violations: list[str] = []
    for phase in definition.phases:
        # A bare name is the only spelling that exists: `allowed_tools` is
        # validated against a fixed vocabulary, so `Bash(gh:*)` is refused at
        # load and never reaches here (#1207).
        granted = set(phase.allowed_tools)
        if not granted:
            continue
        for demand in _DEMANDS:
            if granted & demand.satisfied_by:
                continue
            where = demand.locate(phase)
            if where is None:
                continue
            missing = ", ".join(sorted(demand.satisfied_by))
            violations.append(
                f"phase '{phase.id}' must {demand.must} ({where}) but its "
                f"allowed_tools are [{', '.join(phase.allowed_tools)}] - none of "
                f"[{missing}]. Either grant one or drop the requirement; do not "
                f"ship the pair."
            )
    return violations


#: What ends an `artifacts/input/...` reference written in prose.
#:
#: Prompts are markdown, so a reference is nearly always fenced in backticks
#: and often followed by a comma or a closing bracket. `\S+` would swallow all
#: of that and turn every reference into a non-id.
_REFERENCE_ENDS = r"\s`'\"),;\]}"

#: A phase prompt naming the artifact directory of ANOTHER phase.
#:
#: This finds CANDIDATES only. It deliberately does not encode the phase-id
#: grammar - `_referenced_phase` asks `is_phase_id` that - because the copy of
#: the grammar that used to live here is what #1298 tripped over: it left the
#: `.` out, so `artifacts/input/premise.old.md` matched its longest legal
#: prefix `premise` and the gate reported a dead reference as a live one.
#:
#: The trailing `\.?` is a sentence period, not part of an id. Without it the
#: unfenced `... at artifacts/input/premise.md.` reads as a reference to a
#: phase named `premise.md.`, which the grammar does permit. Note which way
#: that error runs: it invents a missing phase rather than resolving to an
#: existing one, so a mistake here is loud. Do NOT "simplify" this by
#: stripping trailing dots from the captured text instead - that turns a
#: reference to `premise.` into a reference to `premise`, which is the #1298
#: false negative rebuilt by hand.
_INPUT_REF = re.compile(rf"artifacts/input/([^{_REFERENCE_ENDS}]+?)\.?(?=[{_REFERENCE_ENDS}]|$)")


def _referenced_phase(tail: str) -> str | None:
    """The phase id a prompt reference names, or None when it names no id.

    `tail` is whatever followed `artifacts/input/`. Two shapes reach here,
    because two are what the injection layer creates: the durable directory
    `<phase-id>/...`, and the flat `<phase-id>.md` alias kept for one release
    (#988). Anything else - a `<phase-id>` placeholder, a bare `artifacts/input/`,
    a path that is not an id at all - names no phase, and saying so is the
    whole job: the caller must never be handed a prefix of what it passed in.
    """
    head = tail.split("/", 1)[0].removesuffix(".md")
    return head if is_phase_id(head) else None


def stale_phase_references(path: Path, *, phase_library_dir: Path | None = None) -> list[str]:
    """Names a phase rename left pointing at something that is no longer there.

    THE INVARIANT: every name that identifies a phase must identify a phase
    that exists, and a phase's inputs must name one that ran before it.

    WHY A GATE AND NOT A README RULE. `workflows/sdlc/README.md` already states
    both halves - prompt files are named for their phase id, and phase ids are
    load bearing because a later phase reads `artifacts/input/<phase-id>` - and
    the reason it gives for the first is that it makes a rename "break loudly
    in one place instead of silently in two". Nothing made it break at all.
    Both halves are prose in two different files, which is the shape a reviewer
    reads past, and it is the same shape `grant_violations` exists for.

    A rename that updates the phase and forgets the prompt after it is the
    worst version, because it fails at RUN time, deep in a workflow, as an
    empty input directory rather than an error. The phase after it then reads
    nothing and proceeds - #1298's `bootstrap` -> `premise` rename touched four
    workflows, and each one had a downstream prompt naming the old id.

    Deliberately keyed on the DIRECTORY name and not on `input_artifacts`. A
    phase declares the artifact TYPES it consumes, never whose they are, so the
    declaration cannot express this and only the prompt says which phase is
    being read.
    """
    definition = WorkflowDefinition.from_file(path, phase_library_dir=phase_library_dir)
    order_of = {phase.id: phase.order for phase in definition.phases}
    violations: list[str] = []

    # prompt_file is consumed by `from_file` - it inlines the body and deletes
    # the key - so the raw mapping is the only place the filename survives.
    raw = yaml.safe_load(path.read_text())
    for raw_phase in raw.get("phases") or []:
        prompt_file = raw_phase.get("prompt_file")
        phase_id = raw_phase.get("id")
        if not isinstance(prompt_file, str) or not isinstance(phase_id, str):
            continue
        if prompt_file.startswith("shared://"):
            # A shared prompt is named for the JOB and reused by phases with
            # different ids; that is the point of the library.
            continue
        if Path(prompt_file).stem != phase_id:
            violations.append(
                f"phase '{phase_id}' reads prompt_file '{prompt_file}', which is "
                f"named for a different phase. Name it '{phase_id}.md' so a "
                f"rename breaks here instead of silently somewhere else."
            )

    for phase in definition.phases:
        referenced = {
            named
            for tail in _INPUT_REF.findall(phase.prompt_template or "")
            if (named := _referenced_phase(tail)) is not None
        }
        for named in sorted(referenced):
            if named not in order_of:
                violations.append(
                    f"phase '{phase.id}' is told to read artifacts/input/{named}, "
                    f"but this workflow has no phase '{named}'. Its input "
                    f"directory will be empty at run time, and nothing will say so."
                )
            elif order_of[named] >= phase.order:
                violations.append(
                    f"phase '{phase.id}' (order {phase.order}) is told to read "
                    f"artifacts/input/{named}, which is order {order_of[named]} - "
                    f"not yet run. Its input directory will be empty at run time."
                )

    return violations


def main() -> int:
    files = _workflow_files()
    if not files:
        print("No workflow YAML found - nothing to validate.")
        return 0

    failures: list[tuple[Path, str]] = []
    checked = 0
    for path in files:
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            failures.append((path, f"unparseable YAML: {exc}"))
            continue
        if not isinstance(raw, dict) or "phases" not in raw:
            # Not a workflow definition (marketplace manifests, fragments).
            continue
        if _is_package_member(path):
            # Package-relative skill refs ('./skills/x') resolve against the
            # plugin root, which only exists when the package is validated as a
            # whole. Validating the file in isolation reports a failure the
            # supported path does not have - `syn workflow validate <dir>`
            # accepts these. Skipped here and covered by the package check.
            continue
        checked += 1
        reason = validate_file(path)
        if reason is not None:
            failures.append((path, reason))
            continue
        # Only once the file is known to load: `grant_violations` re-reads it
        # through `from_file`, which is what raised above.
        failures.extend((path, why) for why in grant_violations(path))
        failures.extend((path, why) for why in stale_phase_references(path))

    for path, why in failures:
        print(f"  FAIL {path.relative_to(_ROOT)}\n       {why}")

    if failures:
        print(f"\n{len(failures)} of {checked} workflow definition(s) are invalid.")
        return 1

    print(f"✅ {checked} workflow definition(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
