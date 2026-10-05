"""Deterministic stub artifacts for ``workflows/sdlc/implement-v3`` (plan 6.1).

Each text carries the sections that phase's prompt requires under "Write to
``artifacts/output/<phase-id>.md``", in the same order and with the same first
line where one is demanded (``CERTIFIED`` for reverify, ``READY`` for
finalize_pr), so the next phase reads the shape it reads in production.
``{execution_id}``, ``{branch}`` and ``{head_sha}`` are filled per execution
by ``StubAgentProfile.render_artifact``. Every phase after premise names the
head in ``HEAD_SHA_LINE``, because the phase after it checks that exact SHA.

When a phase prompt changes what its artifact must contain, change it here.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from syn_perf.loadtest.handoff import HEAD_SHA_LINE

_STUB = "Load-test stub for execution `{execution_id}`; no agent ran."

IMPLEMENT_V3_ARTIFACTS: Final[Mapping[str, str]] = MappingProxyType(
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

One deterministic file, `loadtest/implement.txt`.

## Branch

`{{branch}}`

{HEAD_SHA_LINE}

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
        "fix": f"""# Fix

{_STUB}

## 1. What verification found

Nothing (stub verdict).

## 2. What changed

One deterministic file, `loadtest/fix.txt`.

## 4. Identity

Branch `{{branch}}`.

{HEAD_SHA_LINE}
""",
        "reverify": f"""CERTIFIED

{_STUB}

## Branch and head certified

Branch `{{branch}}`.

{HEAD_SHA_LINE}

## Blocking defects

None (stub verdict).
""",
        "finalize_pr": f"""READY

{_STUB}

Branch: `{{branch}}`

{HEAD_SHA_LINE}
""",
    }
)
