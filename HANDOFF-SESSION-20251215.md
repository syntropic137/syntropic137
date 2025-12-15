# 🔴 HANDOFF: Agent-in-Container E2E Testing Session
## December 15, 2025

> **CRITICAL STATUS**: E2E test is NOT fully working. Multiple gaps between ADR design and implementation.
> **Cost incurred**: ~$100 in API calls with incomplete results.

---

## 📊 Executive Summary

| Component | ADR Design | Current State | Gap |
|-----------|-----------|---------------|-----|
| Token Injection | Sidecar proxy intercepts & injects | Direct env var injection | 🔴 MAJOR |
| GitHub Auth | Sidecar vends GH_TOKEN to `gh` CLI | Only git-credentials file, no GH_TOKEN | 🔴 BROKEN |
| Observability | Events stream to session aggregate | Events NOT being forwarded | 🔴 BROKEN |
| Artifact Storage | MinIO object store | Empty - nothing stored | 🔴 BROKEN |
| Network Isolation | Egress proxy with allowlist | `--network bridge` (wide open) | 🟡 INSECURE |
| Agent Runner | JSONL events to stdout | Events emitted but not captured | 🔴 BROKEN |
| PR Creation | Agent creates PR via `gh pr create` | `gh` CLI fails - no GH_TOKEN | 🔴 BROKEN |

---

## 🎯 What We Were Trying To Do

Run a **full E2E test** of the isolated container execution model:
1. UI triggers workflow execution
2. Workspace container spins up (gVisor/HardenedDocker)
3. Sidecar proxy intercepts API calls, injects tokens
4. Agent runs inside container, creates code, commits, opens PR
5. Events stream back for real-time observability
6. Artifacts stored in MinIO
7. Session shows token usage, operations, cost

**Test workflow**: `water-lightyear-calc` - creates a Python script and opens a PR to `AgentParadise/sandbox_aef-engineer-beta`

---

## ✅ What IS Working

1. **Container Creation**: gVisor/HardenedDocker containers spin up correctly
2. **Image Building**: `aef-workspace-claude:latest` builds with all dependencies
3. **Agent Execution**: `python -m aef_agent_runner` runs inside container
4. **Claude SDK**: `claude-agent-sdk` executes and creates files
5. **Git Credentials**: `.git-credentials` file written with GitHub App token
6. **Git Operations**: Agent can clone, branch, commit (via git CLI)
7. **Network Access**: Container has network access (when `AEF_SECURITY_ALLOW_NETWORK=true`)
8. **Task Injection**: `task.json` written to `/workspace/.context/task.json`
9. **Prompt Template Substitution**: `{{repo_url}}`, `{{execution_id}}` replaced correctly

---

## 🔴 What Is NOT Working

### 1. GH_TOKEN Not Set → `gh` CLI Fails

**Symptom**: Agent tries `gh auth login --web` (interactive login) instead of using token

**Root Cause**: 
- `GitInjector._inject_github_app_credentials()` writes to `.git-credentials` only
- `gh` CLI needs `GH_TOKEN` environment variable
- `env_injector.py` looks for `os.getenv("GH_TOKEN")` which is empty on host

**Evidence**:
```bash
docker exec <container> bash -c 'echo "GH_TOKEN: ${GH_TOKEN}"'
# Output: GH_TOKEN: 
# (empty!)

docker exec <container> cat ~/.git-credentials
# Output: https://x-access-token:ghs_xxx@github.com
# (git credentials ARE there, but gh CLI doesn't use this)
```

**Fix Needed**: 
- Option A: Also export `GH_TOKEN` in `.bashrc` with the installation token
- Option B: Implement sidecar proxy properly (per ADR-022)

### 2. Sidecar Proxy Not Implemented

**ADR-022 Design**:
```
┌─────────────────────────────────────────────────────────┐
│ Isolated Workspace Container                            │
│  ┌───────────────────┐    ┌──────────────────────────┐ │
│  │ Agent Process     │───▶│ Sidecar Proxy            │ │
│  │ (no API keys)     │    │ - Intercepts HTTPS       │ │
│  │                   │    │ - Injects Authorization  │ │
│  └───────────────────┘    │ - Validates endpoints    │ │
│                           └────────────┬─────────────┘ │
└────────────────────────────────────────┼───────────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │ Token Vending Service│
                              │ - Short-lived tokens │
                              │ - Scoped permissions │
                              └──────────────────────┘
```

**Current Reality**:
- No sidecar proxy running
- Tokens injected directly into container environment
- `docker/sidecar-proxy/` exists but not integrated
- `docker/egress-proxy/` exists but not integrated

**Files that exist but aren't used**:
- `docker/sidecar-proxy/token_injector.py`
- `docker/sidecar-proxy/envoy.yaml`
- `docker/egress-proxy/allowlist_addon.py`

### 3. Observability Events Not Forwarded

**Symptom**: Session shows `total_tokens: 0`, `operations: []`

**Root Cause**: 
- `aef_agent_runner` emits JSONL events to stdout
- `WorkflowExecutionEngine._execute_phase_in_container()` streams these
- BUT: The streaming loop was receiving 0 lines (see debug logs)
- The `execute_streaming` may not be correctly capturing stdout

**Code Location**: 
```python
# packages/aef-domain/.../WorkflowExecutionEngine.py:881
async for line in BaseIsolatedWorkspace.execute_streaming(...):
    # This loop may be yielding nothing
```

**Added Debug Logging** (not yet tested):
```python
line_count = 0
async for line in BaseIsolatedWorkspace.execute_streaming(...):
    line_count += 1
    logger.debug("Received line %d: %s", line_count, line[:100])
```

### 4. Artifact Store Empty

**Symptom**: MinIO bucket `aef-artifacts` at http://localhost:9001 shows no files

**Expected**: Agent output artifacts should be stored there

**Possible Causes**:
- Agent doesn't write to `/workspace/artifacts/`
- `collect_artifacts()` not finding files
- Artifact upload to MinIO not happening
- Different code path for container vs host mode

**Investigation Needed**: Check `ArtifactAggregate` and storage adapter

---

## 📁 Key Files Modified Today

| File | Change |
|------|--------|
| `docker/workspace/Dockerfile` | Added `aef-shared` dependency, renamed to `aef-workspace-claude` |
| `docker/workspace/build.sh` | Updated image name |
| `justfile` | Added `workspace-build`, `_workspace-check` |
| `packages/aef-shared/.../workspace.py` | Default image → `aef-workspace-claude:latest` |
| `.env` | Set `AEF_WORKSPACE_DOCKER_IMAGE=aef-workspace-claude:latest` |
| `WorkflowExecutionEngine.py` | Added template substitution, event forwarding (untested) |
| `packages/aef-adapters/.../contract.py` | NEW: Container validation |
| `packages/aef-adapters/.../base.py` | Enhanced error logging in `execute_streaming` |
| `packages/aef-adapters/.../router.py` | Added contract validation call |

---

## 🔧 Environment Configuration

```bash
# .env (root)
AEF_WORKSPACE_DOCKER_IMAGE=aef-workspace-claude:latest
AEF_SECURITY_ALLOW_NETWORK=true
AEF_WORKSPACE_DOCKER_NETWORK=bridge

# GitHub App (configured but token not passed to gh CLI)
AEF_GITHUB_APP_ID=2461312
AEF_GITHUB_INSTALLATION_ID=99311335
AEF_GITHUB_PRIVATE_KEY="..." # base64 encoded
```

---

## 🗺️ Architecture Gaps vs ADRs

### ADR-021: Isolated Workspace Architecture
- ✅ Multiple backends (gVisor, HardenedDocker)
- ✅ Network isolation configurable
- 🔴 Egress proxy NOT implemented (TODO in ADR)
- 🔴 Sidecar proxy NOT integrated

### ADR-022: Secure Token Architecture
- 🔴 Sidecar proxy NOT running
- 🔴 Token vending NOT used for runtime injection
- ⚠️ Tokens injected at container creation (less secure)

### ADR-023: Workspace-First Execution Model
- ✅ Agents run in containers
- ✅ `aef-agent-runner` package works
- 🔴 Events not flowing back to session aggregate
- 🔴 Artifact collection not working

---

## 🔄 Commands Used

```bash
# Start dev stack (builds workspace image if missing)
just dev-force

# Build workspace image manually
just workspace-build

# Run workflow in container mode
source .env && uv run aef workflow run water-lightyear --container

# Check container processes
docker exec <container_id> ps aux

# Check GH_TOKEN in container
docker exec <container_id> bash -c 'echo "GH_TOKEN: ${GH_TOKEN}"'

# Check git credentials
docker exec <container_id> cat ~/.git-credentials

# Check task.json
docker exec <container_id> cat /workspace/.context/task.json
```

---

## 📋 Immediate Fixes Needed (Priority Order)

### P0: Fix GH_TOKEN injection
**Quick fix** (bypasses sidecar design):
```python
# In git.py _inject_github_app_credentials():
# After writing .git-credentials, also export GH_TOKEN
export_cmd = [
    "sh", "-c",
    f'echo "export GH_TOKEN=\'{token}\'" >> ~/.bashrc && '
    f'echo "export GITHUB_TOKEN=\'{token}\'" >> ~/.bashrc'
]
await executor(workspace, export_cmd)
```

### P1: Debug event streaming
- Add logging to confirm lines are received from `docker exec`
- Check if stdout is being captured correctly
- Verify `emit_*` functions output to correct stream

### P2: Fix artifact storage
- Trace artifact collection path
- Verify MinIO upload is called
- Check for container vs host mode differences

### P3: Implement sidecar properly (future)
- Deploy `docker/sidecar-proxy/` alongside workspace container
- Route container traffic through sidecar
- Sidecar calls Token Vending Service for credentials
- Remove direct env var injection

---

## 🧪 Test Commands for Tomorrow

```bash
# 1. After fixing GH_TOKEN, test PR creation
docker run --rm -e GH_TOKEN=<token> aef-workspace-claude:latest gh pr list --repo AgentParadise/sandbox_aef-engineer-beta

# 2. Test event emission
docker run --rm aef-workspace-claude:latest python3 -c "
from aef_agent_runner.events import emit_started, emit_token_usage
emit_started()
emit_token_usage(100, 50)
"

# 3. Manual workflow test with debug
LOG_LEVEL=DEBUG source .env && uv run aef workflow run water-lightyear --container 2>&1 | tee /tmp/workflow.log

# 4. Check artifact path
docker exec <container> ls -la /workspace/artifacts/
```

---

## 📊 Session Evidence

**Last Session ID**: `e2be5f33-b555-42f5-ad93-f9b8959ac26c`

```json
{
  "status": "running",  // or completed with 0 tokens
  "total_tokens": 0,
  "operations": [],
  "started_at": "2025-12-15T09:56:58.777929Z"
}
```

**Container Evidence**:
- Files created: `water_lightyear_calc.py` ✅
- Branch created: `feat/water-lightyear-calc-*` ✅
- Commit made: Yes ✅
- Push: Unknown (need to check)
- PR: NOT created ❌ (gh auth fails)

---

## 📚 Key ADRs to Review

1. `docs/adrs/ADR-021-isolated-workspace-architecture.md` - Isolation design
2. `docs/adrs/ADR-022-secure-token-architecture.md` - Sidecar proxy design
3. `docs/adrs/ADR-023-workspace-first-execution-model.md` - Execution flow

---

## ❓ Open Questions

1. Was the sidecar ever implemented, or just designed?
2. Should we quick-fix by injecting GH_TOKEN directly, or implement sidecar properly?
3. Why are no JSONL events being captured from the runner?
4. Is the artifact collection code path different for container mode?
5. Are we running a different code path than expected?

---

## 🎬 Next Session Starting Point

1. Read this document
2. Fix GH_TOKEN injection (quick fix in `git.py`)
3. Re-run workflow with debug logging
4. Verify events are captured
5. Check artifact storage
6. If time permits, investigate sidecar implementation

---

*Document created: 2025-12-15 10:00 UTC*
*Last workflow run: water-lightyear-calc, Execution ID: f8c89b12-7cc8-47bc-bbc7-a628238b73f7*
