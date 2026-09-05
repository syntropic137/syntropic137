"""WorkspaceProvisionHandler — creates workspace and injects secrets/artifacts (ISS-196).

Extracted from WorkflowExecutionEngine._setup_workspace_for_phase() and
workspace creation (lines 944-958, 1147-1217).

Reports ProvisionWorkspaceCompletedCommand to the aggregate.

ADR-058: Repos are pre-cloned during setup phase. After setup, synthetic
/workspace/AGENTS.md and /workspace/CLAUDE.md are injected with @-imports
of each repo's AGENTS.md and CLAUDE.md, so Claude starts fully hydrated.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ProvisionWorkspaceCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_shared.agents import AgentProvider, require_executable_provider
from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_ANTHROPIC_BASE_URL,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_CLAUDE_SESSION_ID,
    ENV_GITHUB_TOKEN,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from typing import Protocol

    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
        ResolvedClaudePlugin,
    )
    from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
        ArtifactCollector,
    )

    class ClaudePluginMaterializerProtocol(Protocol):
        """Minimal surface the handler needs (issue #726, PR2).

        The concrete implementation lives in ``syn_api.services``; the
        handler depends only on the structural protocol so the domain layer
        does not import the application service module.
        """

        async def fetch_for_workspace(
            self,
            plugins: tuple[ResolvedClaudePlugin, ...],
        ) -> list[tuple[str, bytes]]: ...

    class SkillMaterializerProtocol(Protocol):
        """Minimal surface the handler needs (issue #772).

        Mirrors ``ClaudePluginMaterializerProtocol``: the concrete
        implementation (``syn_api.services.skill_materializer.SkillMaterializer``)
        lives in the application layer, so the domain handler depends only on
        this structural protocol.
        """

        async def fetch_for_workspace(
            self,
            skills: tuple[ResolvedSkill, ...],
        ) -> list[tuple[str, bytes]]: ...


logger = logging.getLogger(__name__)

#: `owner` and `repo`: the two trailing path segments every accepted repo shape
#: ends with, whatever prefix it carries.
_OWNER_REPO_SEGMENTS: Final[int] = 2

# Maps our phase provider values onto the vercel skills-cli --agent keys.
# The skills CLI (pinned 1.5.14 in the workspace images) owns the per-harness
# install location; we only translate our identifier vocabulary to theirs.
# Verify against `skills add --help` inside the image whenever the pin bumps.
_SKILLS_CLI_AGENT_KEYS: dict[str, str] = {
    "claude": "claude-code",
    "codex": "codex",
    "gemini": "gemini-cli",
}

_SKILL_INSTALL_TIMEOUT_SECONDS = 120

# Baked delegation skills live in the agentic-primitives image under this root
# (claude-cli manifest plugins.include: delegation). A delegation-enabled phase
# installs the skill teaching its PRIMARY agent to hand off to the OTHER CLI.
_DELEGATION_SKILL_ROOT = "/opt/agentic/plugins/delegation/skills"
_DELEGATION_TARGET_SKILL: dict[str, str] = {
    AgentProvider.CODEX: "delegating-to-claude-p",  # codex learns to call claude -p
    AgentProvider.CLAUDE: "delegating-to-codex",  # claude learns to call codex exec
}


# Callable types for dependency injection
PromptBuilder = Callable[
    [ExecutablePhase, str, str, str | None, dict[str, str], dict[str, object]],
    Awaitable[str],
]
CommandBuilder = Callable[[ExecutablePhase, str], list[str]]


def _auth_staging_for(provider: str, allow_delegation: bool) -> tuple[bool, bool]:
    """Return ``(include_codex_auth, needs_claude_env)`` for a phase.

    Delegation opt-in stages BOTH auths so the primary agent can shell out to
    the other CLI; otherwise auth is scoped to the phase's single provider (the
    codex ``~/.codex/auth.json`` file for codex phases, the claude env
    otherwise).

    Validates the provider first: ``!= AgentProvider.CODEX`` is a fall-through
    that would hand claude credentials to any unrecognised provider, so an
    unrunnable one must fail before auth is staged into a workspace.
    """
    known = require_executable_provider(provider)
    include_codex_auth = allow_delegation or known is AgentProvider.CODEX
    needs_claude_env = allow_delegation or known is not AgentProvider.CODEX
    return include_codex_auth, needs_claude_env


def _append_claude_plugin_dirs(
    claude_cmd: list[str],
    phase: ExecutablePhase,
) -> None:
    # WHY append after command_builder (issue #726, PR2): the entrypoint of
    # the production base image already discovers baked-in plugins under
    # /opt/agentic/plugins/ via AGENTIC_PLUGIN_FLAGS. Per-workflow
    # ``--plugin-dir`` flags are additive: claude CLI accepts multiple
    # ``--plugin-dir`` instances and merges them. Validated against the
    # production image in cycle-004/dogfood-platform-726/validation-experiment.
    for plugin in phase.claude_plugins:
        claude_cmd.append("--plugin-dir")
        claude_cmd.append(f"/workspace/.syn-plugins/{plugin.name}")


def _check_no_conflicting_skill_versions(skills: tuple[ResolvedSkill, ...]) -> None:
    """Reject a phase whose skills contain two different versions of one skill_name.

    WHY (Task 7 review note, issue #772): identity-triple dedup at the
    workflow/phase merge layer means a workflow-level skill declaration and a
    phase-level override could legitimately resolve to two different
    ``resolved_sha`` values for the same ``skill_name``. Both would
    materialize to the same ``.syn-skills/<skill_name>/`` workspace path,
    silently clobbering one version with the other on disk. Fail fast
    instead of letting the last-materialized write win unnoticed.
    """
    seen_sha_by_name: dict[str, str] = {}
    for skill in skills:
        prior_sha = seen_sha_by_name.get(skill.skill_name)
        if prior_sha is not None and prior_sha != skill.resolved_sha:
            raise SkillInstallFailed(
                skill.skill_name,
                "n/a",
                exit_code=-1,
                stderr=(
                    f"conflicting versions of skill {skill.skill_name!r}: "
                    f"{prior_sha!r} vs {skill.resolved_sha!r}"
                ),
            )
        seen_sha_by_name[skill.skill_name] = skill.resolved_sha


async def _build_agent_env(
    workspace: ManagedWorkspace, session_id: str, repos: Sequence[str]
) -> dict[str, str]:
    """Build agent environment for workspace execution.

    Injects Claude credentials directly into agent env. ANTHROPIC_BASE_URL
    routes SDK traffic through the Envoy sidecar for observability, but auth
    is carried by the credential env var rather than sidecar substitution.

    See ADR-024 (2026-05-01 update) for why the original "proxy-managed"
    placeholder approach was abandoned and this direct injection was adopted.
    """
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

    # TODO(#723): direct injection — short-term only.
    # TODO(#725): replace with sidecar mint-on-demand to (a) restore the
    # "agent never sees raw secrets" invariant and (b) handle workflows >60min
    # past GitHub's hard 1-hour installation token expiry.
    #
    # Mint a GitHub App installation token and inject as GITHUB_TOKEN so the
    # workspace agent's `gh` CLI can read issues/PRs/comments.
    #
    # ROUTED BY THE REPO UNDER WORK (issue #1129). This used to take
    # `installations[0]`, with a comment saying that was "sufficient for
    # single-org dogfood deployments". The deployment stopped being single-org:
    # with two installations, index 0 was the WRONG one, and because `gh`
    # prefers $GITHUB_TOKEN over the repo-scoped entry `setup_phase_secrets.py`
    # writes to hosts.yml, injecting it actively BROKE a credential that
    # already worked:
    #
    #   $ gh api /installation/repositories        # the injected token
    #   {"total_count": 2,  "repos": ["AgentParadise/..."]}
    #   $ GH_TOKEN=<hosts.yml> gh api /installation/repositories
    #   {"total_count": 6,  "repos": ["syntropic137/syntropic137", ...]}
    gh_token = await _resolve_github_app_token(repos)
    if gh_token:
        env[ENV_GITHUB_TOKEN] = gh_token

    return env


def _repo_full_names(repos: Sequence[str]) -> list[str]:
    """`owner/repo` for each entry, first occurrence first, unparseable ones dropped.

    Accepts the shapes the platform stores: a full URL with or without `.git`,
    an `owner/repo` shorthand, and `git@` / `ssh://` remotes.
    """
    names: list[str] = []
    for repo in repos:
        text = repo.strip().removesuffix(".git")
        if "github.com" in text:
            _, _, tail = text.partition("github.com")
            text = tail.lstrip(":/")
        parts = [part for part in text.split("/") if part]
        if len(parts) >= _OWNER_REPO_SEGMENTS:
            name = f"{parts[-2]}/{parts[-1]}"
            if name not in names:
                names.append(name)
    return names


async def _resolve_github_app_token(repos: Sequence[str]) -> str | None:
    """Mint an installation token for the repo under work.

    ASKS GITHUB WHICH INSTALLATION OWNS THE REPO, rather than listing every
    installation and matching account logins. `GET /repos/{owner}/{repo}/
    installation` is authoritative and is what `setup_phase_secrets.py` already
    uses, so both credential paths now resolve the same way and cannot disagree.

    The list-and-match version this replaced had the original bug back by
    another route: `list_installations` issues one unpaginated request, GitHub
    pages that endpoint at 30, and an owner sitting on page two matched nothing
    (#1129, found in review).

    NO REPOS IS NOT A ROUTING FAILURE. A `requires_repos: false` workflow has no
    repo to route on, and nine in-tree workflows are that shape. Returning None
    for them would remove GitHub access entirely - setup only writes hosts.yml
    when it has repo tokens - so they keep the previous behaviour of the first
    installation, with the arbitrariness stated rather than implied.

    Returns None when the App is not configured, or when a repo IS named and no
    installation owns it: a token from elsewhere cannot reach that repo and
    would displace the repo-scoped hosts.yml credential `gh` would otherwise
    use, which is strictly worse than no token at all.
    """
    try:
        from syn_adapters.github import GitHubAppClient
        from syn_adapters.github.client_endpoints import (
            get_installation_for_repo,
            list_installations,
        )
        from syn_adapters.github.client_token import get_installation_token
        from syn_shared.settings.github import GitHubAppSettings

        github_settings = GitHubAppSettings()
        if not github_settings.is_configured:
            return None

        repo_names = _repo_full_names(repos)

        async with GitHubAppClient(github_settings) as client:
            if not repo_names:
                installations = await list_installations(client)
                if not installations:
                    return None
                logger.info(
                    "No repo to route the GitHub token on (repo-less workflow); "
                    "using the first installation"
                )
                return await get_installation_token(client, str(installations[0]["id"]))

            for name in repo_names:
                try:
                    installation_id = await get_installation_for_repo(client, name)
                except Exception:
                    logger.debug("No GitHub App installation owns %s", name, exc_info=True)
                    continue
                return await get_installation_token(client, installation_id)

            logger.warning(
                "No GitHub App installation owns any of %s; leaving GITHUB_TOKEN unset "
                "so the repo-scoped hosts.yml credential is used",
                repo_names,
            )
            return None
    except Exception as exc:
        logger.warning("Could not mint GitHub App token for agent env: %s", exc)
        return None


class ProvisionResult:
    """Result of workspace provisioning."""

    __slots__ = (
        "agent_env",
        "claude_cmd",
        "command",
        "workspace",
        "workspace_cm",
    )

    def __init__(
        self,
        workspace: ManagedWorkspace,
        workspace_cm: AbstractAsyncContextManager[ManagedWorkspace],
        agent_env: dict[str, str],
        claude_cmd: list[str],
        command: ProvisionWorkspaceCompletedCommand,
    ) -> None:
        self.workspace = workspace
        self.workspace_cm = workspace_cm  # async context manager for cleanup
        self.agent_env = agent_env
        self.claude_cmd = claude_cmd
        self.command = command


class WorkspaceProvisionHandler:
    """Creates workspace, pre-clones repos, injects context files, builds CLI command.

    Reports ProvisionWorkspaceCompletedCommand.

    ADR-058: repos are cloned during setup phase (not by the agent). After setup,
    synthetic /workspace/AGENTS.md and /workspace/CLAUDE.md are injected so the
    agent starts with full project context from turn 1.
    """

    def __init__(
        self,
        workspace_service: WorkspaceService,
        prompt_builder: PromptBuilder,
        command_builder: CommandBuilder,
        claude_plugin_materializer: ClaudePluginMaterializerProtocol | None = None,
        skill_materializer: SkillMaterializerProtocol | None = None,
    ) -> None:
        self._workspace_service = workspace_service
        self._prompt_builder = prompt_builder
        self._command_builder = command_builder
        # WHY optional (issue #726, PR2): existing tests construct the handler
        # without a materializer, and any phase whose ``claude_plugins`` tuple
        # is empty does not need one. The handler short-circuits the
        # materialization branch when the field is empty, so passing None is
        # safe in those cases.
        self._claude_plugin_materializer = claude_plugin_materializer
        # WHY optional (issue #772): mirrors the plugin materializer above,
        # but unlike plugins, a phase that declares skills with no
        # materializer wired is a hard error (see
        # ``_materialize_and_install_skills``) rather than a silent skip.
        self._skill_materializer = skill_materializer

    async def handle(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        workflow_id: str,
        session_id: str,
        repos: list[str] | None = None,
        artifacts: ArtifactCollector | None = None,
        completed_phase_ids: list[str] | None = None,
        phase_outputs: PhaseOutputCache | None = None,
        inputs: dict[str, object] | None = None,
    ) -> ProvisionResult:
        """Provision workspace for a phase.

        Args:
            todo: The to-do item being dispatched.
            phase: The executable phase definition.
            workflow_id: Workflow aggregate ID.
            session_id: Agent session ID for this phase.
            repos: Full GitHub URLs to clone and hydrate context from.
            artifacts: Artifact collector for previous-phase injection.
            completed_phase_ids: Phase IDs completed before this one.
            phase_outputs: What each previous phase produced - the primary
                deliverable for prompt substitution, and every file it wrote so
                the previous phases' output TREES can be rebuilt (#988).
            inputs: Workflow execution inputs dict.
        """
        assert todo.phase_id is not None

        outputs = phase_outputs if phase_outputs is not None else PhaseOutputCache()
        effective_repos = repos or []
        workspace_cm = self._workspace_service.create_workspace(
            execution_id=todo.execution_id,
            workflow_id=workflow_id,
            phase_id=todo.phase_id,
            with_sidecar=True,
            inject_tokens=True,
        )

        # Enter the async context manager; clean up on any exception (P0: container leak fix)
        workspace = await workspace_cm.__aenter__()
        try:
            include_codex_auth, _ = _auth_staging_for(
                phase.agent_config.provider,
                phase.agent_config.allow_delegation,
            )
            await self._hydrate_workspace(
                workspace,
                effective_repos,
                clone_repos=phase.clone_repos,
                include_codex_auth=include_codex_auth,
            )
            await self._materialize_claude_plugins(workspace, phase)
            await self._materialize_and_install_skills(workspace, phase)
            await self._install_baked_delegation_skill(workspace, phase)
            await self._inject_phase_artifacts(
                workspace, artifacts, completed_phase_ids or [], outputs, todo
            )
            return await self._build_provision_result(
                workspace,
                workspace_cm,
                todo,
                phase,
                workflow_id,
                session_id,
                effective_repos,
                outputs.primary,
                inputs,
            )
        except BaseException as exc:
            await workspace_cm.__aexit__(type(exc), exc, exc.__traceback__)
            raise

    async def _hydrate_workspace(
        self,
        workspace: ManagedWorkspace,
        effective_repos: list[str],
        *,
        clone_repos: bool,
        include_codex_auth: bool,
    ) -> None:
        """Run setup phase and inject synthetic context files (ADR-058).

        ``clone_repos=False`` (#1187) still hands the full repo list to
        ``SetupPhaseSecrets``, so the phase keeps its per-repo git credentials
        and its gh hosts.yml entry; only the checkout is skipped. What the
        workspace ends up CONTAINING is the one thing that changes, which is
        why the synthetic context below is derived from it too.
        """
        from syn_adapters.workspace_backends.service import SetupPhaseSecrets

        secrets = await SetupPhaseSecrets.create(
            repositories=effective_repos,
            clone_repos=clone_repos,
            require_github=bool(effective_repos),
            include_codex_auth=include_codex_auth,
        )
        setup_result = await workspace.run_setup_phase(secrets)
        if setup_result.exit_code != 0:
            detail = setup_result.stderr or f"exit code {setup_result.exit_code} (no stderr output)"
            msg = f"Setup phase failed: {detail}"
            raise RuntimeError(msg)
        logger.info("Setup phase completed, secrets cleared")

        # Inject synthetic AGENTS.md + CLAUDE.md (ADR-058)
        # Both files are identical: direct @-imports of each repo's AGENTS.md and
        # CLAUDE.md. Direct imports keep repo content at L2 (not L3 via indirection),
        # preserving maximum @import depth for repo-internal context.
        #
        # Only for repos that are actually ON DISK. Every line of this file is
        # `@/workspace/repos/<name>/...`, so emitting it for a phase that did
        # not clone would point the agent at paths that do not exist.
        cloned_repos = effective_repos if clone_repos else []
        context = self._generate_workspace_context(cloned_repos)
        if context:
            await workspace.inject_files(
                [("AGENTS.md", context.encode()), ("CLAUDE.md", context.encode())]
            )
            logger.info(
                "Injected /workspace/AGENTS.md + CLAUDE.md (%d repo(s))", len(cloned_repos)
            )

    async def _materialize_claude_plugins(
        self,
        workspace: ManagedWorkspace,
        phase: ExecutablePhase,
    ) -> None:
        """Inject resolved claude plugin trees into the workspace (issue #726).

        Runs after secrets clear and the AGENTS.md context inject, so the
        plugin trees land alongside the agent's project context but are
        never visible to the setup script. The orchestrator emits
        ``--plugin-dir`` flags in ``_build_provision_result`` so the agent
        actually loads them.
        """
        if not phase.claude_plugins:
            return
        if self._claude_plugin_materializer is None:
            # WHY warn-instead-of-raise: a workflow that declares plugins but
            # is dispatched through a code path that forgot to wire the
            # materializer should still execute (no plugins is degraded but
            # not broken). Surfaces clearly in logs for the operator.
            logger.warning(
                "Phase %s declared claude_plugins but no materializer is wired; "
                "skipping plugin materialization (issue #726)",
                phase.phase_id,
            )
            return
        plugin_files = await self._claude_plugin_materializer.fetch_for_workspace(
            phase.claude_plugins
        )
        if plugin_files:
            await workspace.inject_files(plugin_files)
            logger.info(
                "Materialized %d claude plugin file(s) across %d plugin(s) into %s",
                len(plugin_files),
                len(phase.claude_plugins),
                workspace.workspace_id,
            )

    async def _materialize_and_install_skills(
        self,
        workspace: ManagedWorkspace,
        phase: ExecutablePhase,
    ) -> None:
        """Inject skill trees and install them for the phase's harness (issue #772).

        Unlike the plugin path, this FAILS FAST: a phase that declares skills
        must get them or must not run. Silent skill-less execution produces
        confusing agent behavior that is worse than a loud provisioning error.
        """
        if not phase.skills:
            return
        _check_no_conflicting_skill_versions(phase.skills)
        if self._skill_materializer is None:
            msg = (
                f"phase {phase.phase_id} declares skills but no skill materializer "
                "is wired; refusing to run the agent without them (issue #772)"
            )
            raise RuntimeError(msg)
        # Resolve the skills-CLI agent key from the phase's provider
        # (claude / codex) - the harness that will actually run.
        agent_selector = phase.agent_config.provider
        agent_key = _SKILLS_CLI_AGENT_KEYS.get(agent_selector)
        if agent_key is None:
            raise SkillInstallFailed(
                phase.skills[0].skill_name,
                agent_selector,
                exit_code=-1,
                stderr=f"no skills-cli agent key for agent {agent_selector!r}",
            )
        skill_files = await self._skill_materializer.fetch_for_workspace(phase.skills)
        if skill_files:
            await workspace.inject_files(skill_files)
        for skill in phase.skills:
            result = await workspace.execute(
                [
                    "skills",
                    "add",
                    f"/workspace/.syn-skills/{skill.skill_name}",
                    "--agent",
                    agent_key,
                    "-y",
                ],
                timeout_seconds=_SKILL_INSTALL_TIMEOUT_SECONDS,
                working_directory="/workspace",
            )
            if result.exit_code != 0:
                raise SkillInstallFailed(
                    skill.skill_name,
                    agent_key,
                    result.exit_code,
                    result.stderr or result.stdout or "",
                )
        logger.info(
            "Installed %d skill(s) for agent %s in %s",
            len(phase.skills),
            agent_key,
            workspace.workspace_id,
        )

    async def _inject_phase_artifacts(
        self,
        workspace: ManagedWorkspace,
        artifacts: ArtifactCollector | None,
        completed_ids: list[str],
        outputs: PhaseOutputCache,
        todo: TodoItem,
    ) -> None:
        """Inject artifacts from previous phases into the workspace."""
        if artifacts is not None:
            await artifacts.inject_from_previous_phases_explicit(
                workspace,
                completed_ids,
                outputs.primary,
                execution_id=todo.execution_id,
                phase_files=outputs.files,
            )

    async def _build_provision_result(
        self,
        workspace: ManagedWorkspace,
        workspace_cm: AbstractAsyncContextManager[ManagedWorkspace],
        todo: TodoItem,
        phase: ExecutablePhase,
        workflow_id: str,
        session_id: str,
        effective_repos: list[str],
        outputs: dict[str, str],
        inputs: dict[str, object] | None,
    ) -> ProvisionResult:
        """Build prompt, CLI command, and return the ProvisionResult."""
        # repo_url for {{repo_url}} prompt substitution (backward compat — uses first repo)
        repo_url_for_prompt = effective_repos[0] if effective_repos else None
        prompt = await self._prompt_builder(
            phase, todo.execution_id, workflow_id, repo_url_for_prompt, outputs, inputs or {}
        )
        claude_cmd = self._command_builder(phase, prompt)
        # `--plugin-dir` is a claude-only flag; appending it to a `codex exec`
        # argv (after the prompt) produces an invalid command, so restrict the
        # plugin-dir augmentation to the claude headless path.
        if phase.agent_config.provider != AgentProvider.CODEX:
            _append_claude_plugin_dirs(claude_cmd, phase)

        # Codex authenticates via the injected ~/.codex/auth.json file, NOT the
        # claude env creds; a codex phase must not receive CLAUDE_CODE_OAUTH_TOKEN /
        # ANTHROPIC_API_KEY (cross-provider secret exposure), so it gets an empty
        # agent env.
        _, needs_claude_env = _auth_staging_for(
            phase.agent_config.provider,
            phase.agent_config.allow_delegation,
        )
        agent_env = (
            await _build_agent_env(workspace, session_id, effective_repos)
            if needs_claude_env
            else {}
        )
        assert todo.phase_id is not None
        command = ProvisionWorkspaceCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workspace_id=workspace.workspace_id,
            session_id=session_id,
        )
        return ProvisionResult(
            workspace=workspace,
            workspace_cm=workspace_cm,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            command=command,
        )

    @staticmethod
    def _repo_name(url: str) -> str:
        """Return repo name from a full GitHub URL.

        Examples:
            "https://github.com/org/repo-a.git" → "repo-a"
            "https://github.com/org/repo-b/"   → "repo-b"
        """
        return url.rstrip("/").split("/")[-1].removesuffix(".git")

    @staticmethod
    async def _install_baked_delegation_skill(
        workspace: ManagedWorkspace, phase: ExecutablePhase
    ) -> None:
        """Install the baked delegation skill for a delegation-enabled phase.

        Rides #772's ``skills add`` seam (harness-agnostic), sourced from the
        image's baked ``delegation`` plugin instead of a registered/materialized
        skill - the base-skill (tier 1) surfacing that #772 plan-1 does not yet
        generalize. ``allow_delegation`` itself only stages both auths (see
        ``_auth_staging_for``); this teaches the primary agent HOW to hand off to
        the other CLI. No-op when the phase does not opt in.
        """
        cfg = phase.agent_config
        if not cfg.allow_delegation:
            return
        # Install the skill teaching the PRIMARY agent to call the OTHER CLI.
        skill_name = _DELEGATION_TARGET_SKILL.get(cfg.provider)
        agent_key = _SKILLS_CLI_AGENT_KEYS.get(cfg.provider)
        if skill_name is None or agent_key is None:
            # allow_delegation is validated headless-only (claude/codex); defensive.
            return
        result = await workspace.execute(
            [
                "skills",
                "add",
                f"{_DELEGATION_SKILL_ROOT}/{skill_name}",
                "--agent",
                agent_key,
                "-y",
            ],
            timeout_seconds=_SKILL_INSTALL_TIMEOUT_SECONDS,
            working_directory="/workspace",
        )
        if result.exit_code != 0:
            raise SkillInstallFailed(
                skill_name, agent_key, result.exit_code, result.stderr or result.stdout or ""
            )
        logger.info(
            "Installed baked delegation skill %s for agent %s in %s",
            skill_name,
            agent_key,
            workspace.workspace_id,
        )

    @staticmethod
    def _generate_workspace_context(repos: list[str]) -> str:
        """Generate content for both /workspace/CLAUDE.md and /workspace/AGENTS.md.

        Both files receive identical content: direct @-imports of each repo's
        AGENTS.md then CLAUDE.md. Direct imports (not via an intermediary file)
        keep repo content at depth L2, leaving L3-L5 for repo-internal imports
        within Claude Code's 5-level absolute limit. Non-existent files are
        silently ignored by Claude Code's @import system.

        AGENTS.md is the Linux Foundation AAIF standard (Dec 2025), loaded by 15+
        platforms. CLAUDE.md is required because Claude Code does not auto-load
        AGENTS.md (issue #6235). Both files ensure full hydration regardless of
        which platform runs the agent.
        """
        if not repos:
            return ""
        lines: list[str] = []
        for url in repos:
            name = WorkspaceProvisionHandler._repo_name(url)
            lines.append(f"@/workspace/repos/{name}/AGENTS.md")
            lines.append(f"@/workspace/repos/{name}/CLAUDE.md")
        return "\n".join(lines) + "\n"
