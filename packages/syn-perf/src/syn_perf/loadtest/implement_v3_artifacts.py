"""Deterministic stub artifacts for ``workflows/sdlc/implement-v3`` (plan 6.1).

Each text carries the sections that phase's prompt requires under "Write to
``artifacts/output/<phase-id>.md``", in the same order and with the same first
line where one is demanded (``Round: N of 2`` for each fix round, ``CERTIFIED``
or ``BLOCKED`` then the round for each reverify, ``READY`` or ``DRAFT`` then
``Repair rounds: N of 2`` for finalize_pr, all from the profile's planned
run), so the next phase reads the shape it reads in production. The rounds
and the ``of N`` they count against are read from the workflow the stubs are
built for, never written here, so a change to the cap reaches them unedited.
``{execution_id}``, ``{branch}``, ``{head_sha}`` and ``{pull_request}`` (the
draft implement opened, as number and URL) are filled per execution by
``ScriptedAgentProfile.render_artifact``. Every phase after premise names the
head in ``HEAD_SHA_LINE``, because the phase after it checks that exact SHA.

When a phase prompt changes what its artifact must contain, change it here.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from syn_perf.loadtest.handoff import HEAD_SHA_LINE

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration import WorkflowDefinition

ReviewVerdictName = Literal["certified", "blocked"]
"""The words a review phase may report as ``review_verdict`` (``ReviewVerdict``)."""

_STUB = "Load-test stub for execution `{execution_id}`; no agent ran."

_REPAIR_PHASE: Final = re.compile(r"(?P<kind>fix|reverify)(?:_(?P<n>[2-9]|[1-9]\d+))?")
"""A repair round's phase id: ``fix``/``reverify`` for round 1, ``_N`` after (PC-63)."""


def pushed_file(phase_id: str) -> str:
    """The one file ``PushBranch`` commits for ``phase_id``; its report names it."""
    return f"loadtest/{phase_id}.txt"


def _round_id(phase: str, n: int) -> str:
    return phase if n == 1 else f"{phase}_{n}"


def _fix(n: int, rounds: int) -> str:
    return f"""Round: {n} of {rounds}

# Fix

{_STUB}

## 1. What verification found

Nothing (stub verdict).

## 2. What changed

One deterministic file, `{pushed_file(_round_id("fix", n))}`.

## 4. Identity

Branch `{{branch}}`.

{HEAD_SHA_LINE}
"""


def _reverify(n: int, rounds: int) -> str:
    return f"""{{review_verdict}}
Round: {n} of {rounds}

{_STUB}

## Branch and head certified

Branch `{{branch}}`.

{HEAD_SHA_LINE}

## Blocking defects

As scripted by the load-test profile; no review ran.
"""


_FIXED: Final[Mapping[str, str]] = MappingProxyType(
    {
        "premise": f"""# Premise check

## 1. Verdict: Confirmed

{_STUB}

## 2. Evidence

The stub replayed a recorded session in place of checking a premise.

## 3. Files and call paths

None. The stub changes nothing in this phase.
""",
        "implement": f"""# Implement

{_STUB}

## What changed

One deterministic file, `{pushed_file("implement")}`.

## Branch

`{{branch}}`

{HEAD_SHA_LINE}

## Draft PR

{{pull_request}}

## Not done

No product change; this is a load-test run.
""",
        "verify": f"""# Verify

## Verdict

Correct and complete (stub verdict).

{_STUB}

## Gates

Not run by the stub unless the profile's workload is `gates`.

## Head verified

Branch `{{branch}}`.

{HEAD_SHA_LINE}
""",
    }
)
"""The stubs for the phases outside the repair rounds, except finalize_pr."""


def implement_v3_artifacts(workflow: WorkflowDefinition) -> Mapping[str, str]:
    """The stub artifact for every phase of ``workflow``, in workflow order.

    The repair rounds are the workflow's ``fix``/``reverify`` phases, and their
    count is the bound every ``Round: N of M`` and ``Repair rounds: N of M``
    line names. A phase this module has no stub for gets none, so
    ``ScriptedAgentProfile.for_workflow`` reports it missing.
    """
    repairs = [m for p in workflow.phases if (m := _REPAIR_PHASE.fullmatch(p.id))]
    bound = sum(1 for m in repairs if m["kind"] == "fix")
    stubs = {
        **_FIXED,
        **{
            m[0]: (_fix if m["kind"] == "fix" else _reverify)(int(m["n"] or 1), bound)
            for m in repairs
        },
        "finalize_pr": f"""{{outcome}}
Repair rounds: {{repair_rounds}} of {bound}

{_STUB}

PR: {{pull_request}}

Branch: `{{branch}}`

{HEAD_SHA_LINE}
""",
    }
    return MappingProxyType({p.id: stubs[p.id] for p in workflow.phases if p.id in stubs})


IMPLEMENT_V3_REVIEW_VERDICTS: Final[Mapping[str, ReviewVerdictName]] = MappingProxyType(
    {"reverify": "certified"}
)
"""The default run: round one certifies, so the aggregate skips round two and
finalize_pr marks the draft ready. Pass other verdicts to
``ScriptedAgentProfile.for_workflow`` to load-test the repair rounds."""
