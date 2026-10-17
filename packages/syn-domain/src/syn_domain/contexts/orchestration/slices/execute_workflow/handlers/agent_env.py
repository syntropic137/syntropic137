"""The env a Claude agent is launched with, credential included (ADR-024, #1914).

Kept apart from WorkspaceProvisionHandler because it is one of the four places
a host credential is produced, and the WorkspaceCredentialPolicy decides here
whether one is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_ANTHROPIC_BASE_URL,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_CLAUDE_SESSION_ID,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.workspace_credential_policy import (
        WorkspaceCredentialPolicy,
    )


async def build_agent_env(
    workspace: ManagedWorkspace, session_id: str, credential_policy: WorkspaceCredentialPolicy
) -> dict[str, str]:
    """Build agent environment for workspace execution.

    Under ``NoCredentials`` (#1914) the agent gets its session id and nothing
    else: no Claude credential and no proxy, since none was provisioned.

    Injects Claude credentials directly into agent env. ANTHROPIC_BASE_URL
    routes SDK traffic through the Envoy sidecar for observability, but auth
    is carried by the credential env var rather than sidecar substitution.

    See ADR-024 (2026-05-01 update) for why the original "proxy-managed"
    placeholder approach was abandoned and this direct injection was adopted.
    """
    if not credential_policy.supplies_credentials:
        return {ENV_CLAUDE_SESSION_ID: session_id}
    proxy_url = workspace.proxy_url
    if not proxy_url:
        msg = (
            "Shared Envoy proxy not available. "
            "Ensure envoy-proxy service is running and sidecar is enabled."
        )
        raise RuntimeError(msg)

    from syn_shared.settings import get_settings

    settings = get_settings()
    env: dict[str, str] = {
        ENV_CLAUDE_SESSION_ID: session_id,
        ENV_ANTHROPIC_BASE_URL: proxy_url,
    }

    # Prefer OAuth token; fall back to API key. Claude Code CLI v2.1.76+
    # validates credential format locally before sending any HTTP request, so
    # the sidecar-substitution pattern ("proxy-managed" placeholder) no longer
    # works — the CLI rejects it before the proxy gets a chance. ADR-024 updated.
    #
    # TODO(#724): For the API key path specifically, spike whether a syntactically
    # valid placeholder (e.g. "sk-ant-DEADBEEF...") passes the local format check
    # so the Envoy sidecar can substitute the real value on egress. If it works,
    # restore ADR-022/024's "agent never sees raw secrets" invariant for API keys.
    # OAuth is out of scope (ToS gray area for header proxying).
    if settings.claude_code_oauth_token:
        env[ENV_CLAUDE_CODE_OAUTH_TOKEN] = settings.claude_code_oauth_token.get_secret_value()
    elif settings.anthropic_api_key:
        env[ENV_ANTHROPIC_API_KEY] = settings.anthropic_api_key.get_secret_value()
    # No fail-fast here. If neither credential is configured, the workspace
    # agent will exit with "Not logged in" — acceptable for now. A startup-time
    # check that fails the API container with a clear operator message would
    # be cleaner; tracked separately. (Copilot suggested fail-fast in this
    # function, but that breaks smoke tests that exercise the processor loop
    # without configured credentials.)

    # NO GITHUB CREDENTIAL HERE (#725). `gh` used to get an installation token
    # as $GITHUB_TOKEN, which it prefers over hosts.yml - and an environment
    # variable fixed at launch cannot be renewed, so every `gh` call past
    # minute sixty failed. The same credential, chosen by the same
    # repo-under-work routing (#1129), now lives in hosts.yml, written by the
    # setup phase and rewritten by every renewal: see `setup_phase_secrets`.
    # TODO(#725): Tier 1 - a per-workspace credential sidecar that mints on
    # demand, so the agent never holds a raw GitHub token at all.
    return env
