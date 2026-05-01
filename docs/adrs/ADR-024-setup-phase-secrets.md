# ADR-024: Setup Phase Secrets Pattern

## Status

Accepted (with limitations - see 2026-01-29 update below)

## Date

2025-12-15 (Updated: 2026-01-29)

## Context

The Syntropic137 executes agent code in isolated containers that need access to:

- **Claude API** - For LLM inference
- **GitHub API** - For repository operations (clone, commit, push, PR)

### Previous Approach (ADR-022)

ADR-022 proposed a **sidecar proxy pattern** (Envoy-based) where:
- Agent containers never hold raw API keys
- Sidecar proxy intercepts requests and injects tokens
- Token Vending Service issues short-lived, scoped tokens

While this provides excellent security, it introduces significant complexity:
- Additional Envoy container per workspace (~50MB RAM)
- Complex Envoy configuration (ext_authz filter, clusters, listeners)
- Token injection HTTP service
- Docker network orchestration
- New Docker image to build/maintain

**Estimated implementation: 2-3 days**

### Industry Research

We researched how production AI agent platforms handle this:

| Platform | Approach |
|----------|----------|
| **OpenAI Codex** | Secrets available during setup phase, **removed before agent runs** |
| **E2B** | Environment variables passed to sandbox (simpler, less secure) |
| **Devin** | GitHub App integration, platform manages tokens |

OpenAI Codex's approach is particularly elegant:
> "Secrets are stored with an additional layer of encryption and are only decrypted for task execution. **They are only available to setup scripts. For security reasons, secrets are removed from the environment when the agent is running.**"
> — [Codex Cloud Environments Docs](https://developers.openai.com/codex/cloud/environments/)

## Decision

Implement a **Setup Phase Secrets** pattern inspired by OpenAI Codex:

### 1. Two-Phase Execution Model

```
┌─────────────────────────────────────────────────────────────────┐
│                      WORKSPACE LIFECYCLE                        │
│                                                                 │
│  ┌──────────────────────────┐    ┌────────────────────────────┐ │
│  │     SETUP PHASE          │    │      AGENT PHASE           │ │
│  │                          │    │                            │ │
│  │  Secrets: AVAILABLE      │───▶│  Secrets: CLEARED          │ │
│  │                          │    │                            │ │
│  │  • Clone private repos   │    │  • Agent executes task     │ │
│  │  • Configure git creds   │    │  • Uses cached credentials │ │
│  │  • gh auth login         │    │  • No raw tokens in env    │ │
│  │  • pip install private   │    │  • Can push via git helper │ │
│  │                          │    │                            │ │
│  │  Duration: ~30 seconds   │    │  Duration: task-dependent  │ │
│  └──────────────────────────┘    └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2. GitHub App-Only Authentication

**GitHub authentication is EXCLUSIVELY via GitHub App installation tokens.**

No personal access tokens (`GH_TOKEN`, `GITHUB_TOKEN`) are supported. This:
- Reduces cognitive load (one clear auth path)
- Ensures consistent, auditable authentication (all commits from bot identity)
- Provides short-lived, scoped tokens (1 hour TTL)
- Enables per-repository permission scoping

### 3. Setup Script Configures Persistent Credentials

During setup phase, the GitHub App token is used to configure credential helpers that persist after the token is cleared:

```bash
#!/bin/bash
# setup.sh - Runs with secrets available

# Configure Git credential helper with GitHub App token
git config --global credential.helper store
echo "https://x-access-token:${GITHUB_APP_TOKEN}@github.com" > ~/.git-credentials
chmod 600 ~/.git-credentials

# Configure Git identity (from GitHub App bot)
git config --global user.name "${GIT_AUTHOR_NAME}"
git config --global user.email "${GIT_AUTHOR_EMAIL}"

# Configure gh CLI (for PR creation)
mkdir -p ~/.config/gh
cat > ~/.config/gh/hosts.yml << EOF
github.com:
    oauth_token: ${GITHUB_APP_TOKEN}
    user: ${GIT_AUTHOR_NAME}
    git_protocol: https
EOF
chmod 600 ~/.config/gh/hosts.yml

# Clone private repositories
git clone https://github.com/org/repo /workspace/repo

# Secrets will be CLEARED after this script completes
```

### 4. Token Lifecycle

```python
@dataclass
class SetupPhaseSecrets:
    """Secrets available only during setup phase."""

    # Short-lived GitHub App installation token (1 hour max)
    github_app_token: str

    # Claude API key (or short-lived token if using token vending)
    anthropic_api_key: str

    # Git identity (from GitHub App bot, non-sensitive)
    git_author_name: str
    git_author_email: str

    @classmethod
    async def create(cls, *, require_github: bool = True) -> SetupPhaseSecrets:
        """Create secrets using GitHub App.

        Args:
            require_github: If True, raises if GitHub App not configured

        Raises:
            GitHubAppNotConfiguredError: If require_github=True and App not configured
        """
        # Uses GitHub App to generate installation token
        # Bot identity is used for git commits
        ...


class WorkspaceService:
    async def create_workspace(
        self,
        execution_id: str,
    ) -> ManagedWorkspace:
        # 1. Create container WITHOUT secrets in environment
        container = await self._create_container(execution_id)

        # 2. Generate secrets using GitHub App
        secrets = await SetupPhaseSecrets.create()

        # 3. Run setup script WITH secrets
        await workspace.run_setup_phase(secrets)

        # 4. Secrets are CLEARED after setup phase
        # 5. Return workspace ready for agent
        return ManagedWorkspace(container)
```

### 5. Secret Clearing

After setup completes, secrets are aggressively cleared:

```python
async def _clear_secrets(self, container: Container) -> None:
    """Remove all traces of secrets from container."""

    # Clear shell history
    await container.exec(["rm", "-f", "/root/.bash_history", "/root/.zsh_history"])

    # Clear any temp files
    await container.exec(["rm", "-rf", "/tmp/secrets"])

    # Note: GITHUB_APP_TOKEN env var is NOT persisted across docker exec calls
    # Docker exec -e vars are ephemeral to that specific exec call

    # Note: Git credentials remain in ~/.git-credentials (by design)
    # This allows git push without exposing raw token to agent
```

### 6. GitHub App Token Generation

For GitHub operations, we use short-lived **installation access tokens**:

```python
class GitHubAppTokenProvider:
    """Generates short-lived tokens from GitHub App."""

    async def get_installation_token(
        self,
        installation_id: str,
        repository: str,
        permissions: dict[str, str],
    ) -> str:
        """Generate installation access token.

        - TTL: 1 hour (GitHub's limit)
        - Scoped to specific repository
        - Limited permissions (e.g., contents: write, pull_requests: write)
        """
        jwt = self._generate_app_jwt()

        response = await self._http.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {jwt}"},
            json={
                "repositories": [repository],
                "permissions": permissions,
            },
        )

        return response.json()["token"]
```

## Consequences

### Positive

✅ **Simple Implementation**
- No sidecar containers
- No Envoy configuration
- Standard Docker operations

✅ **Fast to Deploy**
- Can be implemented in hours, not days
- Unblocks E2E testing immediately

✅ **Battle-Tested Pattern**
- Used by OpenAI Codex at scale
- Proven in production AI agent platforms

✅ **Good Security Posture**
- Secrets only exist during brief setup phase (~30 seconds)
- Agent never has access to raw tokens in environment
- GitHub operations use credential helper (not raw token)

### Negative

⚠️ **Brief Exposure Window**
- Secrets exist in container for ~30 seconds during setup
- Malicious setup scripts could exfiltrate (mitigated by controlled scripts)

⚠️ **Git Credentials Persist**
- `~/.git-credentials` contains token for duration of execution
- Agent could theoretically read this file
- Mitigated by: short TTL tokens, repo-scoped permissions

⚠️ **Not Zero-Trust**
- Unlike sidecar pattern, there is a window where secrets are present
- Acceptable for single-tenant, controlled deployments
- May need sidecar (ADR-022) for multi-tenant production

### Security Comparison

| Aspect | Raw Env Vars | Setup Phase (This) | Sidecar (ADR-022) |
|--------|-------------|-------------------|-------------------|
| Token in agent env | ❌ Yes | ✅ No (after setup) | ✅ No |
| Implementation complexity | Low | Low | High |
| Prompt injection risk | High | Medium | Low |
| Suitable for untrusted agents | ❌ No | ⚠️ Limited | ✅ Yes |
| Time to implement | Immediate | Hours | Days |

## Implementation

### Phase 1: Basic Setup Phase (MVP)

1. Add `run_setup_script()` to `WorkspaceService`
2. Clear environment variables after setup
3. Configure git credential helper during setup
4. Test with GitHub push/PR operations

### Phase 2: GitHub App Integration

1. Generate installation access tokens (1-hour TTL)
2. Scope tokens to specific repositories
3. Limit permissions to required operations

### Phase 3: Additional Encryption (Optional)

Following Codex's pattern:
> "Secrets are stored with an additional layer of encryption"

1. Encrypt secrets at rest in Redis/database
2. Decrypt only at setup time
3. Use execution-specific encryption keys

## Related ADRs

- **ADR-021**: Isolated Workspace Architecture (container security)
- **ADR-022**: Secure Token Architecture (sidecar pattern, on hold)
- **ADR-023**: Workspace-First Execution Model

## References

- [OpenAI Codex Cloud Environments](https://developers.openai.com/codex/cloud/environments/)
- [GitHub App Installation Tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
- [Git Credential Storage](https://git-scm.com/docs/git-credential-store)

---

## 2026-01-29 Update: Scope Limitation

### This ADR Works for GitHub, NOT Anthropic

**Important clarification**: The Setup Phase Secrets pattern works well for **GitHub authentication** but does NOT solve the **Anthropic API key** problem.

| Secret | Setup Phase Works? | Why |
|--------|-------------------|-----|
| **GITHUB_APP_TOKEN** | ✅ Yes | Git credential helper persists auth without raw token |
| **ANTHROPIC_API_KEY** | ❌ No | Claude CLI/SDK needs key at runtime for HTTP requests |

### Current Implementation Gap

In `WorkflowExecutionEngine.py`, the Anthropic API key is still passed directly:

```python
# GitHub: ✅ Uses credential helper (ADR-024 pattern)
# Anthropic: ❌ Raw key exposed to agent
if secrets.anthropic_api_key:
    agent_env["ANTHROPIC_API_KEY"] = secrets.anthropic_api_key
```

### Why No "Credential Helper" for HTTP APIs

Git has a credential helper mechanism - configure once, subsequent `git push` commands work without seeing the token.

HTTP APIs (like Anthropic's) have no equivalent:
- Each request needs the `x-api-key` header
- Claude CLI reads `ANTHROPIC_API_KEY` from environment
- No way to "cache" auth like git does

### Path Forward

For Anthropic API key security, implement **ADR-022 (Shared Envoy Cluster)**:

```
Agent Container                    Envoy Proxy
ANTHROPIC_BASE_URL=proxy:8080  →  Injects x-api-key  →  api.anthropic.com
(no API key!)                     (holds the key)
```

See:
- ADR-022: Secure Token Architecture (updated 2026-01-29)
- Issue #43: Implementation tracking

### Acceptable Risk for Single-Tenant

The current implementation (Anthropic key exposed) is acceptable ONLY for:
- ✅ Single-tenant experimentation
- ✅ Controlled deployments with trusted prompts
- ❌ NOT acceptable for multi-tenant production
- ❌ NOT acceptable for untrusted agent code

---

## 2026-04-09 Update: Multi-Repository Support (ADR-058)

This update documents changes to `SetupPhaseSecrets` introduced by workspace hydration ([ADR-058](ADR-058-workspace-hydration.md)).

### New `repositories` Field

`SetupPhaseSecrets` now carries the list of repositories to clone during setup:

```python
@dataclass(frozen=True)
class SetupPhaseSecrets:
    # NEW: GitHub URLs of repositories to clone during setup
    repositories: list[str]

    # SUPERSEDED: single github_app_token replaced by repo_tokens (see below)
    # github_app_token: str | None  ← no longer present

    # NEW: per-repo token — maps full repo URL → installation access token
    repo_tokens: dict[str, str]

    # Unchanged
    anthropic_api_key: str
    git_author_name: str
    git_author_email: str
```

### `create()` Factory Changes

The `create()` classmethod now accepts a `repositories` parameter and resolves tokens per GitHub App installation rather than per-workflow:

```python
@classmethod
async def create(
    cls,
    *,
    repositories: list[str] | None = None,
    require_github: bool = True,
) -> SetupPhaseSecrets:
    ...
```

**Token resolution algorithm** (see ADR-058 for full detail):

1. For each repo URL, call `GET /repos/{owner}/{repo}/installation` to get `installation_id`.
2. If any repo returns **404** → re-raise immediately before cloning begins. The lookup error propagates as-is (fail fast with the offending URL in the error message).
3. Group repos by `installation_id` (one installation covers all repos in an org/account).
4. For each unique `installation_id`, call `POST /app/installations/{id}/access_tokens` once.
5. Build `repo_tokens: dict[str, str]` — full repo URL → token.

The backward-compatible single-repo path (`_repository_url` fallback) still works: one repo → one installation lookup → same token written as before, just under the new `repo_tokens` structure.

### `build_setup_script()` Replaces `DEFAULT_SETUP_SCRIPT`

Direct use of the `DEFAULT_SETUP_SCRIPT` constant is replaced by a `build_setup_script()` method on `SetupPhaseSecrets`. This method:

1. Writes the standard credential and git identity setup (unchanged from before).
2. Writes **per-repo** credential entries to `~/.git-credentials` instead of one blanket `github.com` entry:

```
https://x-access-token:TOKEN_A@github.com/org/repo-a
https://x-access-token:TOKEN_A@github.com/org/repo-b
https://x-access-token:TOKEN_B@github.com/personal/repo-c
```

3. Appends `git clone` commands for each repo with idempotency guards:

```bash
mkdir -p /workspace/repos

[ -d "/workspace/repos/repo-a" ] || git clone "https://github.com/org/repo-a" "/workspace/repos/repo-a"
[ -d "/workspace/repos/repo-b" ] || git clone "https://github.com/org/repo-b" "/workspace/repos/repo-b"
```

### Summary of Changes

| Aspect | Before (ADR-024) | After (ADR-058) |
|--------|-----------------|-----------------|
| GitHub token field | `github_app_token: str \| None` | `repo_tokens: dict[str, str]` |
| Token resolution | One token for the execution | One token per unique installation ID |
| `~/.git-credentials` | One blanket `github.com` entry | Per-repo URL entries |
| Setup script source | `DEFAULT_SETUP_SCRIPT` constant | `build_setup_script()` method |
| Repo cloning | Not in setup phase | Appended by `build_setup_script()` |
| Auth failure mode | Silent / runtime git error | Fail fast before any cloning |
| Multi-org support | Not supported | Supported via per-installation tokens |

---

## 2026-05-01 Update: Claude Credential Injection (Agent Phase)

### The proxy-managed pattern no longer works for Claude credentials

The 2026-01-29 update identified that Claude CLI authentication could not follow the setup-phase pattern used for GitHub and pointed at ADR-022 (shared Envoy proxy with sidecar token substitution) as the path forward. Specifically, ADR-022 proposed setting `CLAUDE_CODE_OAUTH_TOKEN="proxy-managed"` in the agent env, and having the token-injector sidecar swap the real credential value on outgoing HTTPS requests before they reached `api.anthropic.com`.

**This substitution path does not work with Claude Code CLI v2.1.76+.** The CLI performs a client-side credential format check before making any API call:

| Credential source | Expected format | `"proxy-managed"` result |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `sk-ant-oat01-…` | ❌ fails format check |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | ❌ fails format check |
| On-disk credentials file | valid JSON at `~/.claude/credentials.json` | ❌ file absent |

If all three checks fail, the CLI exits immediately with `Not logged in · Please run /login` — no HTTP request is issued, the sidecar never sees anything to substitute.

### Decision: direct injection into agent env

The real credential is injected directly into the agent phase environment in `_build_agent_env` (`WorkspaceProvisionHandler.py`). OAuth token is preferred; API key is the fallback:

```python
if settings.claude_code_oauth_token:
    env[ENV_CLAUDE_CODE_OAUTH_TOKEN] = settings.claude_code_oauth_token.get_secret_value()
elif settings.anthropic_api_key:
    env[ENV_ANTHROPIC_API_KEY] = settings.anthropic_api_key.get_secret_value()
```

`ANTHROPIC_BASE_URL` still routes SDK traffic through the Envoy sidecar for observability purposes — the sidecar sees the token on outgoing requests and can log it but does not need to substitute it.

### Security posture change

This deviates from the original "agent phase never sees raw secrets" invariant. The revised posture:

| Property | Previous goal | Current reality |
|---|---|---|
| Agent env holds real credential | ❌ no | ✅ yes (via env var) |
| Subagents inherit credential | ❌ no | ✅ yes (env is inherited) |
| Credential visible in `/proc/self/environ` | ❌ no | ✅ yes (agent process) |
| Credential visible to sidecar | ✅ yes (substitution) | ✅ yes (on outgoing requests) |
| Credential cleared after phase | ✅ yes | ❌ no (env stays for phase duration) |

Acceptable risk framing (from 2026-01-29 update, still applies):
- ✅ Single-tenant deployments with trusted agent code
- ✅ Self-hosted instances with controlled workloads
- ❌ Multi-tenant production (agent code cannot be fully trusted)
- ❌ Untrusted marketplace workflows without additional sandboxing

### What would restore the original invariant

If a future Claude Code CLI version supports any of the following, the original ADR-022 pattern can be reinstated:

1. A `--skip-auth-check` or `--bare` flag that defers auth to the server response (does not exist as of v2.1.76).
2. A credential-helper interface for HTTP APIs analogous to `git credential-helper`.
3. On-disk credential pre-population during setup phase (the `~/.claude/credentials.json` file format is not publicly documented; this may be viable if the format is discovered or stabilizes).

### Per-credential injection matrix

Different secret types have very different risk profiles. The platform handles each according to its lifetime, scope, and ToS posture:

| Credential | Lifetime | Scope | Current strategy | Risk class | Follow-up |
|---|---|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | months/years | account-wide, full spend | direct env injection | **HIGH** — accepted; ToS gray area precludes header proxying | none — direct injection is the long-term posture |
| `ANTHROPIC_API_KEY` | indefinite | account-wide, full spend | direct env injection (fallback when OAuth absent) | **HIGH** — accepted short-term | TODO #724 — spike sidecar substitution with valid-format placeholder |
| `GH_TOKEN` (GitHub App installation token) | 1 hour | per-installation, repo-scoped | direct env injection (planned) | **LOW** — already short-lived and scoped | TODO #723 — implement direct injection; #725 — sidecar mint-on-demand for >60min tasks |
| `GH_TOKEN` (user PAT, dev fallback) | user-set | user-defined | direct env injection (operator-controlled) | **MEDIUM** — operator owns it | none — user controls scope |

### Long-running task ceiling

GitHub App installation tokens are hard-capped at **1 hour** by GitHub. As Claude Code agent runs grow longer (model capability + multi-phase orchestration), workflow executions exceeding 60 minutes will hit mid-execution 401s on any `gh` or `git push` call. The direct-injection path (#723) does not solve this; the sidecar mint-on-demand pattern (#725) does, by transparently refreshing the token on every outgoing GitHub call.

Migration plan: ship #723 first to unblock the common case (sub-60min workflows). Land #725 before it becomes a blocker — track wall-clock distribution of workflow executions to know when that's imminent.

### TODOs in implementation

Code paths that violate ADR-024's original "agent never sees raw secrets" invariant carry inline TODO comments referencing the relevant follow-up issue:

- `_build_agent_env` in `WorkspaceProvisionHandler.py` — TODO #724 (Claude API key sidecar spike)
- (future) `_build_agent_env` once `GH_TOKEN` injection lands — TODO #725 (GH App sidecar mint-on-demand)

These TODOs are an explicit reminder that direct injection is a deliberate compromise documented in this ADR, not an oversight.
