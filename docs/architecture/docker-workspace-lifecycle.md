# Docker Workspace Lifecycle & Setup Phase Secrets

**Last Updated:** 2026-01-26  
**Reference:** [ADR-024: Setup Phase Secrets Pattern](../adrs/ADR-024-setup-phase-secrets.md)

---

## Overview

Syn137 executes agent code in **isolated Docker containers** with a two-phase lifecycle inspired by OpenAI Codex:

1. **Setup Phase** - Secrets available, configure persistent credentials (~30 seconds)
2. **Agent Phase** - Secrets cleared, agent executes task using cached credentials

This pattern provides excellent security while maintaining usability.

---

## Workspace Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Creating: workspace.create()
    
    Creating --> SetupPhase: Container started
    
    state SetupPhase {
        [*] --> SecretsAvailable
        state SecretsAvailable {
            [*] --> EnvVarsSet
            EnvVarsSet --> note1: GITHUB_APP_TOKEN ✓
            EnvVarsSet --> note2: ANTHROPIC_API_KEY ✓
        }
        
        SecretsAvailable --> ConfigureGit
        state ConfigureGit {
            [*] --> CredHelper: git config credential.helper store
            CredHelper --> WriteCredFile: echo token > ~/.git-credentials
            WriteCredFile --> SetPermissions: chmod 600
        }
        
        ConfigureGit --> ConfigureGH
        state ConfigureGH {
            [*] --> GHAuth: gh auth login --with-token
            GHAuth --> GHConfig: gh config set git_protocol https
        }
        
        ConfigureGH --> ConfigureIdentity
        state ConfigureIdentity {
            [*] --> SetName: git config user.name
            SetName --> SetEmail: git config user.email
        }
        
        ConfigureIdentity --> SecretsCached
        SecretsCached --> [*]
    }
    
    SetupPhase --> AgentPhase: Clear secrets from environment
    
    state AgentPhase {
        [*] --> EnvCleared
        state EnvCleared {
            [*] --> note3: GITHUB_APP_TOKEN ❌ (removed)
            [*] --> note4: ANTHROPIC_API_KEY ✓ (kept)
        }
        
        EnvCleared --> RunAgent
        state RunAgent {
            [*] --> ClaudeCLI: claude -p "task prompt"
            ClaudeCLI --> UseGitCredHelper: git operations
            UseGitCredHelper --> note5: Uses cached credentials
        }
        
        RunAgent --> [*]
    }
    
    AgentPhase --> Cleanup: Task complete or error
    Cleanup --> Destroyed: Container removed
    Destroyed --> [*]
    
    note right of SetupPhase
        Setup Phase (~30 seconds)
        ========================
        • Raw tokens AVAILABLE
        • Configure persistence
        • GitHub App (1hr TTL)
        • No agent code runs yet
    end note
    
    note right of AgentPhase
        Agent Phase (task-dependent)
        ============================
        • GitHub token REMOVED
        • Claude key still available
        • Uses cached credentials
        • Agent can push via git
    end note
```

---

## Two-Phase Execution Model

### Phase 1: Setup (Secrets Available)

```mermaid
sequenceDiagram
    participant WS as WorkspaceService
    participant Container as Docker Container
    participant Setup as setup.sh
    participant Git as Git Config
    participant GH as gh CLI
    
    WS->>Container: docker run with secrets
    activate Container
    
    Note over Container: Environment variables:<br/>GITHUB_APP_TOKEN=ghs_xxx<br/>ANTHROPIC_API_KEY=sk-ant-xxx
    
    Container->>Setup: Run setup.sh
    activate Setup
    
    Setup->>Git: git config credential.helper store
    Setup->>Git: echo "https://x-access-token:$TOKEN@github.com"<br/>> ~/.git-credentials
    Setup->>Git: chmod 600 ~/.git-credentials
    
    Setup->>Git: git config user.name "$GIT_AUTHOR_NAME"
    Setup->>Git: git config user.email "$GIT_AUTHOR_EMAIL"
    
    Setup->>GH: echo $GITHUB_APP_TOKEN | gh auth login
    Setup->>GH: gh config set git_protocol https
    
    Setup-->>Container: Setup complete ✓
    deactivate Setup
    
    Note over Container: Credentials now cached:<br/>- ~/.git-credentials<br/>- ~/.config/gh/hosts.yml<br/>- ~/.gitconfig
    
    Container-->>WS: Ready for agent execution
    deactivate Container
```

**Duration:** ~30 seconds

**What Happens:**
1. Docker container starts with secrets in environment
2. `setup.sh` script runs with full token access
3. Git credential helper configured with GitHub App token
4. `gh` CLI authenticated for PR operations
5. Git identity configured (author name/email)
6. Credentials persisted to disk, environment cleared

### Phase 2: Agent Execution (Secrets Cleared)

```mermaid
sequenceDiagram
    participant WS as WorkspaceService
    participant Container as Docker Container
    participant Agent as Claude CLI
    participant Git as Git Operations
    participant GH as GitHub API
    
    WS->>Container: Clear GITHUB_APP_TOKEN from environment
    activate Container
    
    Note over Container: Environment after clear:<br/>GITHUB_APP_TOKEN ❌ (removed)<br/>ANTHROPIC_API_KEY ✓ (kept for Claude)
    
    WS->>Agent: claude -p "Implement feature X"
    activate Agent
    
    Agent->>Agent: LLM reasoning<br/>(uses ANTHROPIC_API_KEY)
    Agent->>Git: git clone, commit, push
    activate Git
    
    Note over Git: Git reads credentials from:<br/>~/.git-credentials<br/>(no env var needed)
    
    Git->>GH: HTTPS with cached token
    GH-->>Git: Success
    deactivate Git
    
    Agent->>GH: gh pr create<br/>(via gh CLI)
    activate GH
    
    Note over GH: gh reads auth from:<br/>~/.config/gh/hosts.yml<br/>(no env var needed)
    
    GH-->>Agent: PR created
    deactivate GH
    
    Agent-->>WS: Task complete
    deactivate Agent
    deactivate Container
```

**Duration:** Task-dependent (minutes to hours)

**What Happens:**
1. GitHub App token removed from environment
2. Agent executes with only Claude API key in env
3. Git operations use credential helper (reads from disk)
4. `gh` CLI uses cached authentication
5. Agent cannot access raw tokens even if compromised
6. All git/GitHub operations work normally

---

## Security Model

### Token Lifecycle

```mermaid
gantt
    title Token Security Lifecycle
    dateFormat X
    axisFormat %S sec
    
    section Setup Phase
    GITHUB_APP_TOKEN in environment :active, 0, 30
    ANTHROPIC_API_KEY in environment :active, 0, 30
    Configure credential helpers :milestone, 25, 0
    
    section Agent Phase
    GITHUB_APP_TOKEN in environment :done, 30, 3600
    ANTHROPIC_API_KEY in environment :active, 30, 3600
    Credentials available via helpers :active, 25, 3600
    Agent code executes :active, 30, 3600
```

### Key Security Properties

| Property | Description | Enforcement |
|----------|-------------|-------------|
| **Time-limited** | GitHub App tokens expire in 1 hour | GitHub App platform |
| **Scope-limited** | Tokens scoped to specific repositories | GitHub App permissions |
| **Phase-separated** | Raw tokens only in setup, not during execution | WorkspaceService clears env |
| **Credential caching** | Git operations use cached creds, not env vars | Git credential helper |
| **No token leakage** | Agent code can't read GITHUB_APP_TOKEN | Not in process environment |
| **Audit trail** | All GitHub operations from bot identity | GitHub App audit logs |

---

## GitHub App Integration

### Why GitHub App (Not PAT)?

**GitHub App advantages:**
- ✅ **Short-lived tokens** (1 hour TTL vs indefinite PAT)
- ✅ **Repository-scoped** permissions
- ✅ **Bot identity** (not personal account)
- ✅ **Audit trail** (all commits from bot)
- ✅ **Revocable** at installation level

**Personal Access Token (PAT) disadvantages:**
- ❌ Long-lived (weeks/months)
- ❌ Account-wide permissions
- ❌ Personal identity (commits as you)
- ❌ Harder to revoke
- ❌ Less secure for automation

### Token Request Flow

```mermaid
sequenceDiagram
    participant WS as WorkspaceService
    participant GHA as GitHub App Service
    participant GitHub as GitHub API
    participant Container as Docker Container
    
    WS->>GHA: Request installation token<br/>(for repo)
    GHA->>GHA: Load GitHub App private key
    GHA->>GHA: Create JWT (signed with key)
    GHA->>GitHub: POST /app/installations/{id}/access_tokens<br/>(with JWT)
    GitHub-->>GHA: Installation token (1hr TTL)
    GHA-->>WS: Token
    
    WS->>Container: docker run<br/>GITHUB_APP_TOKEN=ghs_xxx
    
    Note over Container: Token valid for 1 hour,<br/>then automatically expires
```

---

## Implementation Details

### Setup Script Example

```bash
#!/bin/bash
# setup.sh - Runs with secrets available

set -euo pipefail

echo "🔧 Configuring Git credentials..."

# Configure Git credential helper
git config --global credential.helper store
echo "https://x-access-token:${GITHUB_APP_TOKEN}@github.com" > ~/.git-credentials
chmod 600 ~/.git-credentials

# Configure Git identity (from GitHub App bot)
git config --global user.name "${GIT_AUTHOR_NAME}"
git config --global user.email "${GIT_AUTHOR_EMAIL}"

echo "🔐 Configuring gh CLI..."

# Configure gh CLI (for PR creation)
echo "${GITHUB_APP_TOKEN}" | gh auth login --with-token
gh config set git_protocol https

echo "✅ Setup complete - credentials cached"
```

### WorkspaceService Pseudo-code

```python
async def execute_workflow(self, workflow: Workflow) -> ExecutionResult:
    # Phase 1: Setup
    token = await self.github_app.get_installation_token(repo_id)
    
    container = await self.docker.run(
        image="agentic-workspace-claude-cli",
        environment={
            "GITHUB_APP_TOKEN": token,
            "ANTHROPIC_API_KEY": self.anthropic_key,
            "GIT_AUTHOR_NAME": "Syn137 Bot",
            "GIT_AUTHOR_EMAIL": "bot@syn137.dev",
        },
        command=["/workspace/setup.sh"],
    )
    
    await container.wait_for_setup()
    
    # Phase 2: Agent execution (clear GitHub token)
    await container.clear_env_var("GITHUB_APP_TOKEN")
    
    result = await container.exec(
        command=["claude", "-p", workflow.prompt],
        environment={
            # GITHUB_APP_TOKEN removed
            "ANTHROPIC_API_KEY": self.anthropic_key,
        },
    )
    
    return result
```

---

## Comparison with Industry

| Platform | Approach | Security Model |
|----------|----------|----------------|
| **OpenAI Codex** | Setup phase secrets (inspiration) | Secrets removed before agent runs |
| **E2B** | Environment variables | Simpler, less secure (tokens in agent env) |
| **Devin** | GitHub App integration | Platform manages tokens |
| **Syn137** | Setup phase + GitHub App | **Hybrid: Best of both** |

---

## Alternative Considered: Sidecar Proxy (ADR-022)

### Why Not Sidecar?

We initially considered a **sidecar proxy pattern** (Envoy-based):
- Agent containers never hold tokens
- Sidecar intercepts requests, injects tokens
- Zero-trust model

**Why we chose Setup Phase instead:**
- ❌ Sidecar adds ~50MB RAM per workspace
- ❌ Complex Envoy configuration
- ❌ Additional Docker networking
- ❌ New Docker image to maintain
- ❌ Estimated 2-3 days implementation

**Setup Phase wins:**
- ✅ Simpler implementation (~1 day)
- ✅ Fewer moving parts
- ✅ Industry-validated (OpenAI Codex)
- ✅ Good enough security for current threat model

**Future:** Can revisit sidecar if/when multi-tenant isolation is needed.

---

## Failure Modes & Mitigation

### Failure Mode 1: Setup Script Fails
**Impact:** Agent can't execute  
**Mitigation:**
- Comprehensive logging in setup.sh
- Fail fast if credentials not cached
- Retry with exponential backoff

### Failure Mode 2: Token Expires During Execution
**Impact:** Long-running tasks fail  
**Mitigation:**
- GitHub App tokens valid for 1 hour
- Most agent tasks complete in < 30 minutes
- Future: Token refresh mechanism

### Failure Mode 3: Credential Helper Fails
**Impact:** Git operations fail  
**Mitigation:**
- Validate credential helper works in setup phase
- Fail if ~/.git-credentials not created
- Test push to dummy repo in setup

### Failure Mode 4: Agent Reads Setup Logs
**Impact:** Token leakage via logs  
**Mitigation:**
- Mask tokens in all log output
- Setup logs written to separate file, deleted after setup
- No token echo to stdout/stderr

---

## Testing Strategy

### Unit Tests
- ✅ `test_setup_script_configures_git()`
- ✅ `test_setup_script_configures_gh()`
- ✅ `test_token_cleared_after_setup()`

### Integration Tests (ADR-033)
- ✅ `test_agent_can_push_after_setup()`
- ✅ `test_agent_cannot_read_github_token()`
- ✅ `test_gh_pr_create_works()`

### Security Tests
- ✅ `test_token_not_in_process_env()`
- ✅ `test_token_not_in_agent_logs()`
- ✅ `test_credentials_file_permissions()`

---

## Monitoring & Observability

### Metrics
- `workspace_setup_duration_seconds` - Setup phase timing
- `workspace_setup_failures_total` - Setup failures
- `workspace_token_refresh_total` - Token refreshes
- `workspace_git_operation_failures_total` - Git failures

### Logs
- Setup phase: Detailed success/failure logging
- Agent phase: Git operation logging
- Token lifecycle: Request, clear, expire events

### Alerts
- Setup failure rate > 5%
- Token expiry during active execution
- Credential helper failures

---

## Related Documentation

- [ADR-024: Setup Phase Secrets Pattern](../adrs/ADR-024-setup-phase-secrets.md)
- [ADR-022: Secure Token Architecture (Sidecar - on hold)](../adrs/ADR-022-secure-token-architecture.md)
- [ADR-021: Isolated Workspace Architecture](../adrs/ADR-021-isolated-workspace-architecture.md)
- [Infrastructure Data Flow](./infrastructure-data-flow.md)
