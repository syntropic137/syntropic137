"""Token-free load test (issue #1310, capacity plan section 6).

Only the contract exists so far (step 7a): what a stub agent replays and does
in each phase. The stub image (7b) lives in agentic-workspace and reads it as
JSON; the driver (7c) will live beside it here.
"""

from syn_perf.loadtest.handoff import HEAD_SHA_LINE, head_sha_handed_over
from syn_perf.loadtest.scripted_agent_profile import (
    LOADTEST_BRANCH_PREFIX,
    SCRIPTED_AGENT_PROFILE_ENV,
    GatesWorkload,
    NoWorkload,
    OpenPullRequest,
    PushBranch,
    ReportOnly,
    ScriptedAgentProfile,
    ScriptedPhase,
    ScriptedStream,
    SyntheticWorkload,
    VerifyRemoteBranch,
)

__all__ = [
    "HEAD_SHA_LINE",
    "LOADTEST_BRANCH_PREFIX",
    "SCRIPTED_AGENT_PROFILE_ENV",
    "GatesWorkload",
    "NoWorkload",
    "OpenPullRequest",
    "PushBranch",
    "ReportOnly",
    "ScriptedAgentProfile",
    "ScriptedPhase",
    "ScriptedStream",
    "SyntheticWorkload",
    "VerifyRemoteBranch",
    "head_sha_handed_over",
]
