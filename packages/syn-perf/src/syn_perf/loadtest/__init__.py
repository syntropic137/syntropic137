"""Token-free load test (issue #1310, capacity plan section 6).

The contract (step 7a) says what a stub agent replays and does in each phase;
the stub image (7b) lives in agentic-workspace and reads it as JSON. The
driver (7c, #1717) is ``python -m syn_perf.loadtest``: ``driver`` observes a
running stack and ``pass_bar`` judges what it saw.
"""

from syn_perf.loadtest.handoff import HEAD_SHA_LINE, head_sha_handed_over
from syn_perf.loadtest.scripted_agent_profile import (
    LOADTEST_BRANCH_PREFIX,
    SCRIPTED_AGENT_PROFILE_ENV,
    GatesWorkload,
    MarkPullRequestReady,
    NoWorkload,
    OpenDraftPullRequest,
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
    "MarkPullRequestReady",
    "NoWorkload",
    "OpenDraftPullRequest",
    "PushBranch",
    "ReportOnly",
    "ScriptedAgentProfile",
    "ScriptedPhase",
    "ScriptedStream",
    "SyntheticWorkload",
    "VerifyRemoteBranch",
    "head_sha_handed_over",
]
