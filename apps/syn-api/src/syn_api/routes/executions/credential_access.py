"""Claude credential, checked before an execution is accepted (#1948).

A workflow with a Claude phase and no Anthropic credential used to be admitted
and then fail mid-run, while `/health` already reported the
`anthropic_api_key` degraded reason. The refusal asks the same predicate
`/health` asks, so the two cannot disagree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from syn_api.services.credentials import has_claude_credential
from syn_shared.agents import AgentProvider
from syn_shared.env_constants import ENV_ANTHROPIC_API_KEY, ENV_CLAUDE_CODE_OAUTH_TOKEN
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import WorkflowTemplateAggregate

_CREDENTIALS_DOCS = "https://docs.syntropic137.com/docs/guide/secrets#harness-credentials"

MISSING_CLAUDE_CREDENTIAL_DETAIL = (
    "This workflow has a Claude phase, but no Anthropic credential is configured. "
    f"Set {ENV_ANTHROPIC_API_KEY} or {ENV_CLAUDE_CODE_OAUTH_TOKEN} (either one is "
    "enough) and restart the API. On a selfhost install, run "
    "`npx @syntropic137/setup init` to configure it. "
    f"See {_CREDENTIALS_DOCS}"
)


def require_claude_credential(workflow: WorkflowTemplateAggregate) -> None:
    """Raise 422 if a phase runs on Claude and there is no credential for it.

    Phases on other providers need no Anthropic credential, so a workflow
    without a Claude phase is never refused here. Under test settings `/health`
    does not report the credential missing, and neither does this.
    """
    settings = get_settings()
    if settings.is_test or has_claude_credential(settings):
        return
    if any(
        (phase.provider or AgentProvider.CLAUDE) == AgentProvider.CLAUDE
        for phase in workflow.phases
    ):
        raise HTTPException(status_code=422, detail=MISSING_CLAUDE_CREDENTIAL_DETAIL)
