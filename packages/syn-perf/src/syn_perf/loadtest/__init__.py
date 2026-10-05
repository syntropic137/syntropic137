"""Token-free load test (issue #1310, capacity plan section 6).

Only the contract exists so far (step 7a): what a stub agent replays and does
in each phase. The stub image (7b) lives in agentic-workspace and reads it as
JSON; the driver (7c) will live beside it here.
"""

from syn_perf.loadtest.stub_agent_profile import (
    LOADTEST_BRANCH_PREFIX,
    STUB_AGENT_PROFILE_ENV,
    GatesWorkload,
    NoWorkload,
    OpenPullRequest,
    PushBranch,
    ReportOnly,
    StubAgentProfile,
    StubPhase,
    StubStream,
    SyntheticWorkload,
    VerifyRemoteBranch,
)

__all__ = [
    "LOADTEST_BRANCH_PREFIX",
    "STUB_AGENT_PROFILE_ENV",
    "GatesWorkload",
    "NoWorkload",
    "OpenPullRequest",
    "PushBranch",
    "ReportOnly",
    "StubAgentProfile",
    "StubPhase",
    "StubStream",
    "SyntheticWorkload",
    "VerifyRemoteBranch",
]
