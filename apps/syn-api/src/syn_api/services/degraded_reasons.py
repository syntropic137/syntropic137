"""The names /health gives to the ways this API can be up but not fully serving.

Its own module because three things speak this vocabulary and none of them owns
it: `lifecycle` (the service registry that raises most of these), `credentials`
(which raises the two credential ones during startup) and `read_path_health`
(which raises the read-path ones). Kept inside `lifecycle` it forced both of the
others to import lifecycle back, and `credentials` had to do it from inside a
function body to break the cycle.
"""

from __future__ import annotations

from enum import StrEnum


class DegradedReason(StrEnum):
    """Reasons the API may enter degraded mode.

    StrEnum so values serialize directly to JSON in health responses.
    """

    ARTIFACT_STORAGE = "artifact_storage"
    CLAUDE_PLUGIN_STORAGE = "claude_plugin_storage"
    SKILL_STORAGE = "skill_storage"
    CONVERSATION_STORAGE = "conversation_storage"
    SUBSCRIPTION_COORDINATOR = "subscription_coordinator"
    PROJECTION_CATCHUP = "projection_catchup"
    PROJECTION_STALLED = "projection_stalled"
    EVENT_POLLER = "event_poller"
    CHECK_RUN_POLLER = "check_run_poller"
    ANTHROPIC_API_KEY = "anthropic_api_key"
    GITHUB_APP = "github_app"
