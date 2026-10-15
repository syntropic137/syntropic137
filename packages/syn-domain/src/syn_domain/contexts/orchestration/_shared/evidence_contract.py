"""The three documents an evidence gate exchanges, and nothing that moves them.

ADR-014 §10 and docs/plans/20261015_platform-dispatched-evidence.md §A.1/§A.6.
An evidence gate sits between two phases. Three documents cross it, and each
crosses a trust boundary, so each is parsed here exactly once:

  - `EvidenceRequest`: a phase asks the platform for proof, inside its
    `TASK_RESULT`. Written by an agent.
  - `EvidenceReport`: `evidence.json`, which the target repository's evidence
    workflow uploads. Written by code in the PR under test.
  - `EvidenceManifest`: `manifest.json`, which the platform writes from its own
    events, and the only document `finalize_pr` trusts.

Their JSON Schemas are generated from these models and checked in under
`schemas/evidence/` (`scripts/export_evidence_schemas.py`), so the scripts that
write `evidence.json` in other repositories validate against the same contract.

This module is contracts only. Nothing here dispatches, waits or decides when a
gate opens (§A.3-§A.8 land in later PRs).
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

#: The grammar `scripts/mutation_evidence.py` enforces on its `tests` input
#: (`_NODE_ID_RE`): `path/to/test_x.py` then zero or more `::Name`, the last may
#: carry a parametrize id. One grammar, so a request this accepts is one the
#: workflow accepts.
NODE_ID_PATTERN: Final = (
    r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.py"
    r"(::[A-Za-z_][A-Za-z0-9_]*)*(::[A-Za-z_][A-Za-z0-9_]*\[[A-Za-z0-9_.,=+-]*\])?$"
)
#: The same limit `scripts/mutation_evidence.py` puts on one dispatch.
MAX_TESTS: Final = 50

HeadSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
TestNodeId = Annotated[str, StringConstraints(pattern=NODE_ID_PATTERN)]
RepositoryName = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$")
]
PullRequestNumber = Annotated[int, Field(ge=1, le=9_999_999)]
#: `scripts/mutation_evidence.py` `_DISPATCH_ID_RE`: empty for a manual run.
DispatchId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{0,64}$")]
Count = Annotated[int, Field(ge=0)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvidenceKind(StrEnum):
    """What a phase can ask for. Each maps to `<kind>-evidence.yml` in the target repository."""

    MUTATION = "mutation"
    INTEGRATION = "integration"


class EvidenceVerdict(StrEnum):
    """What one evidence run concluded, in `evidence.json`."""

    PASSED = "passed"
    FAILED = "failed"
    VOID = "void"


class TestOutcome(StrEnum):
    """What happened to one requested node id in an evidence run."""

    __test__ = False  # a vocabulary, not a pytest class

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    XFAIL = "xfail"
    NOT_COLLECTED = "not_collected"


class EvidenceStepKind(StrEnum):
    """A step of a gate's plan. The last two are platform-internal: no phase can declare them."""

    MUTATION = "mutation"
    INTEGRATION = "integration"
    REMOVE_MUTATION_PATCHES = "remove_mutation_patches"
    REQUIRED_CHECK = "required_check"


class StepOutcome(StrEnum):
    """How a step settled. `unavailable` means no evidence exists, not that evidence failed."""

    PASSED = "passed"
    FAILED = "failed"
    VOID = "void"
    UNAVAILABLE = "unavailable"


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceRequest(_Contract):
    """One entry of a phase's `TASK_RESULT` `evidence` list."""

    kind: EvidenceKind
    repository: RepositoryName
    branch: Annotated[str, StringConstraints(min_length=1)]
    pr: PullRequestNumber
    head_sha: HeadSha
    tests: Annotated[tuple[TestNodeId, ...], Field(min_length=1, max_length=MAX_TESTS)]


class RequestedTestResult(_Contract):
    id: TestNodeId
    outcome: TestOutcome


class SuiteCounts(_Contract):
    collected: Count
    passed: Count
    failed: Count
    skipped: Count


class EvidenceReport(_Contract):
    """`evidence.json`, schema 1: what one evidence workflow run found on one head."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    # `schema` on the wire; renamed here because BaseModel.schema() is taken.
    schema_version: Literal[1] = Field(alias="schema")
    kind: EvidenceKind
    pr: PullRequestNumber
    head_sha: HeadSha
    dispatch_id: DispatchId
    verdict: EvidenceVerdict
    requested: Annotated[tuple[RequestedTestResult, ...], Field(min_length=1)]
    suite: SuiteCounts
    summary: str
    report_md: str

    @model_validator(mode="after")
    def _passed_means_every_requested_test_passed(self) -> Self:
        ids = [result.id for result in self.requested]
        if len(set(ids)) != len(ids):
            raise ValueError("requested names the same node id twice")
        if self.verdict is not EvidenceVerdict.PASSED:
            return self
        # §A.1: a requested id that did not run and pass voids an integration
        # run, and a red or skipped baseline voids a mutation run (§A.14). A
        # report claiming `passed` over one is a forgery or a bug, never proof.
        unproven = [r.id for r in self.requested if r.outcome is not TestOutcome.PASSED]
        if unproven:
            raise ValueError(f"verdict is passed but requested tests did not pass: {unproven}")
        if self.kind is EvidenceKind.INTEGRATION and self.suite.failed:
            raise ValueError("an integration verdict of passed needs a suite with no failures")
        return self


class StepRef(_Contract):
    """Where a reused result was first settled."""

    gate_id: Annotated[str, StringConstraints(min_length=1)]
    step: Count


class ManifestStep(_Contract):
    """One planned step of a gate, as the events recorded it."""

    index: Count
    kind: EvidenceStepKind
    outcome: StepOutcome
    reason: Reason | None = None
    run_url: str | None = None
    head_sha: HeadSha | None = None
    reused_from: StepRef | None = None

    @model_validator(mode="after")
    def _no_evidence_says_why(self) -> Self:
        if self.outcome in (StepOutcome.VOID, StepOutcome.UNAVAILABLE) and self.reason is None:
            raise ValueError(f"a {self.outcome.value} step must carry a reason")
        return self


class PatchRemoval(_Contract):
    """The provenance of the platform's S -> S' commit, which keeps evidence about S valid at S'."""

    before_sha: HeadSha
    after_sha: HeadSha
    author: Annotated[str, StringConstraints(min_length=1)]

    @model_validator(mode="after")
    def _moves_the_head(self) -> Self:
        if self.before_sha == self.after_sha:
            raise ValueError("a patch removal must move the head: before_sha equals after_sha")
        return self


class EvidenceManifest(_Contract):
    """`manifest.json`: every planned step of one gate, written from events once all settled."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schema")
    gate_id: Annotated[str, StringConstraints(min_length=1)]
    steps: Annotated[tuple[ManifestStep, ...], Field(min_length=1)]
    patch_removal: PatchRemoval | None = None
    # A manifest is written only after the last step settles; a partial one
    # must not parse, so a missing step can never read as "all passed".
    complete: Literal[True]

    @model_validator(mode="after")
    def _steps_are_the_whole_plan(self) -> Self:
        if [step.index for step in self.steps] != list(range(len(self.steps))):
            raise ValueError("steps must be indexed 0..n-1 in order, with none missing")
        removed = any(
            step.kind is EvidenceStepKind.REMOVE_MUTATION_PATCHES
            and step.outcome is StepOutcome.PASSED
            for step in self.steps
        )
        # §A.5: Removed/Adopted record the provenance and then settle `passed`;
        # HeadMoved settles `void`. Finalize trusts S -> S' only from here.
        if removed != (self.patch_removal is not None):
            raise ValueError(
                "patch_removal is present exactly when a remove_mutation_patches step passed"
            )
        return self


#: File name under `schemas/evidence/` -> the model it is generated from.
SCHEMA_FILES: Final[tuple[tuple[str, type[BaseModel]], ...]] = (
    ("evidence-request.schema.json", EvidenceRequest),
    ("evidence-report.schema.json", EvidenceReport),
    ("evidence-manifest.schema.json", EvidenceManifest),
)


def render_schema(model: type[BaseModel]) -> str:
    """The checked-in text of a model's JSON Schema, as written and as compared."""
    document = model.model_json_schema(by_alias=True, mode="validation")
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
