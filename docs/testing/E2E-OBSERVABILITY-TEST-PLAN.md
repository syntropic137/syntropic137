# End-to-End Observability Test Plan

**Version:** 1.0
**Date:** 2024-12-15
**Purpose:** Validate complete observability pipeline from agent execution → event store → projections → API → UI

---

## Test Scope

This E2E test validates:
1. **Docker Container**: Agent execution with hook instrumentation
2. **Event Store**: Domain events persisted correctly
3. **Projections**: Cost and operation aggregations
4. **API Layer**: REST endpoints serving correct data
5. **UI Dashboard**: Real-time observability metrics
6. **GitHub Integration**: GitHub App authentication and PR creation

---

## Prerequisites

```bash
# 1. Environment configured
cp .env.example .env
# Ensure GH_APP_ID, GH_APP_PRIVATE_KEY, GH_APP_INSTALLATION_ID set

# 2. Services running
just dev-up

# 3. Fresh workspace image
just workspace-build
```

---

## Test Execution

### Step 1: Execute Workflow

```bash
# Run GitHub PR workflow in container
just cli workflow run github-pr --container

# Expected output:
# ✓ Workflow started: execution_id=<EXEC_ID>
# ✓ Agent running in isolated workspace
# ✓ Streaming events...

# Save execution ID for validation
export EXEC_ID="<execution_id_from_output>"
```

**Validation:**
- Command completes successfully (exit code 0)
- Execution ID returned in output
- No error messages in CLI

---

### Step 2: Validate Docker Container Logs

```bash
# Get container name
docker ps --filter "name=syn-workspace" --format "{{.Names}}"

# View container logs
docker logs <container_name> 2>&1 | less

# Or follow real-time
docker logs -f <container_name>
```

**Expected in Logs:**
```json
{"event_type": "token_usage", "input_tokens": 1234, "output_tokens": 567, ...}
{"event_type": "tool_use", "tool_name": "bash", ...}
{"event_type": "tool_result", "tool_name": "bash", ...}
```

**Validation:**
- ✓ JSONL events on stdout (one per line)
- ✓ `token_usage` events with model info
- ✓ `tool_use` events for each tool call (bash, computer, text_editor)
- ✓ `tool_result` events with success/error status
- ✓ No Python exceptions or tracebacks
- ✓ Agent completes task (PR creation)

---

### Step 3: Validate Event Store

```bash
# Query event store directly
just cli exec psql postgresql://aef:aef@localhost:5432/aef_dev

# SQL queries
SELECT
    event_type,
    COUNT(*) as count
FROM events
WHERE aggregate_id = '$EXEC_ID'
GROUP BY event_type;

# Expected results:
# event_type                  | count
# AgentObservation            | 50+
# WorkflowExecutionStarted    | 1
# PhaseExecutionStarted       | 3
# PhaseExecutionCompleted     | 3
# WorkflowExecutionCompleted  | 1
```

**Deep Validation:**
```sql
-- Check AgentObservation events
SELECT
    (data->>'observation_type') as obs_type,
    COUNT(*) as count
FROM events
WHERE event_type = 'AgentObservation'
  AND aggregate_id = '$EXEC_ID'
GROUP BY obs_type;

-- Expected:
-- obs_type         | count
-- TOKEN_USAGE      | 10+
-- TOOL_STARTED     | 15+
-- TOOL_COMPLETED   | 15+
-- PROMPT_SUBMITTED | 3+
```

**Validation:**
- ✓ All event types present
- ✓ AgentObservation events > 50
- ✓ TOKEN_USAGE events exist
- ✓ TOOL_STARTED/COMPLETED pairs match
- ✓ Event timestamps in correct order

---

### Step 4: Validate Projections (Cost Tracking)

```bash
# Query cost projections
curl -s http://localhost:8000/api/v1/executions/$EXEC_ID | jq '{
  total_cost: .total_cost,
  input_tokens: .input_tokens,
  output_tokens: .output_tokens,
  cache_creation_tokens: .cache_creation_tokens,
  cache_read_tokens: .cache_read_tokens,
  tool_calls: .tool_calls,
  model: .model,
  turns: .turns
}'

# Expected output:
{
  "total_cost": "0.0234",        # > 0 (calculated)
  "input_tokens": 12450,         # > 0
  "output_tokens": 3200,         # > 0
  "cache_creation_tokens": 5000, # > 0 (likely)
  "cache_read_tokens": 8000,     # > 0 (likely)
  "tool_calls": 18,              # > 0 (not zero!)
  "model": "claude-sonnet-4-20250514",
  "turns": 12                    # > 0
}
```

**Validation:**
- ✓ `total_cost` > 0 (not null, not "0.00")
- ✓ `input_tokens` and `output_tokens` > 0
- ✓ `tool_calls` > 0 (**critical: was showing 0 before fix**)
- ✓ `model` matches agent config
- ✓ `turns` reflects conversation length
- ✓ Cache tokens present (if prompt caching used)

---

### Step 5: Validate API Endpoints

```bash
# 5.1 Execution detail
curl -s http://localhost:8000/api/v1/executions/$EXEC_ID | jq .

# 5.2 Session list (should have 3 sessions for github-pr workflow)
curl -s http://localhost:8000/api/v1/executions/$EXEC_ID/sessions | jq 'length'
# Expected: 3

# 5.3 Session detail (check first session)
export SESSION_ID=$(curl -s http://localhost:8000/api/v1/executions/$EXEC_ID/sessions | jq -r '.[0].session_id')
curl -s http://localhost:8000/api/v1/sessions/$SESSION_ID | jq '{
  tool_calls: .tool_calls,
  total_cost: .total_cost,
  model: .model
}'

# 5.4 Artifacts (should include PR URL)
curl -s http://localhost:8000/api/v1/executions/$EXEC_ID/artifacts | jq '.[] | select(.name == "pr_url")'
```

**Validation:**
- ✓ All endpoints return 200 OK
- ✓ Execution has 3 sessions
- ✓ Each session has `tool_calls > 0`
- ✓ Artifacts include `pr_url` with GitHub PR link
- ✓ No 500 errors or null values

---

### Step 6: Validate UI Dashboard

```bash
# Open dashboard
open http://localhost:5173/executions/$EXEC_ID
```

**Manual Validation Checklist:**

#### Execution Detail Page
- [ ] **Status**: Shows "completed" with green indicator
- [ ] **Total Cost**: Displays calculated cost (e.g., "$0.02")
- [ ] **Tool Calls**: Shows count > 0 (**was 0 before fix**)
- [ ] **Token Metrics**:
  - [ ] Input tokens > 0
  - [ ] Output tokens > 0
  - [ ] Cache tokens displayed (if applicable)
- [ ] **Timeline**: Shows phase progression
- [ ] **Sessions**: Lists 3 sessions

#### Session Detail Page (click into a session)
- [ ] Session-level metrics displayed
- [ ] Tool calls list visible
- [ ] Token usage per session
- [ ] Conversation turns visible

#### Operations Tab
- [ ] Tool usage events listed
- [ ] Each tool shows:
  - [ ] Tool name (bash, computer, text_editor)
  - [ ] Start/end timestamps
  - [ ] Duration
  - [ ] Token usage (if captured)

---

### Step 7: Validate GitHub Integration

```bash
# 7.1 Check GitHub App authentication
# Should have used installation token (not personal token)
docker logs <container_name> 2>&1 | grep -i "github"

# 7.2 Verify PR created
export PR_URL=$(curl -s http://localhost:8000/api/v1/executions/$EXEC_ID/artifacts | jq -r '.[] | select(.name == "pr_url") | .data.url')
echo "PR URL: $PR_URL"

# 7.3 Open PR in browser
open "$PR_URL"
```

**GitHub PR Validation:**
- [ ] PR exists on target repository
- [ ] PR title matches workflow config
- [ ] PR description contains agent-generated content
- [ ] PR author is GitHub App bot
- [ ] Branch created successfully
- [ ] No authentication errors in logs

---

## Success Criteria

All layers validated:

- [x] **Container Layer**: Agent executes, emits JSONL events
- [x] **Event Store**: Domain events persisted with correct types
- [x] **Projection Layer**: Cost/operations aggregated correctly
- [x] **API Layer**: Endpoints return accurate data
- [x] **UI Layer**: Dashboard displays all metrics (including tool calls!)
- [x] **GitHub Layer**: PR created via GitHub App

**Critical Metrics:**
- `tool_calls > 0` (not zero!)
- `total_cost > 0` (calculated from token usage)
- `token_usage` events → cost projections → API → UI

---

## Common Issues & Debugging

### Issue: Tool Calls = 0 in UI

**Root Cause:** `TOOL_COMPLETED` events not processed by projections

**Debug:**
```bash
# Check if events exist in event store
psql ... -c "SELECT COUNT(*) FROM events WHERE event_type='AgentObservation' AND data->>'observation_type'='TOOL_COMPLETED';"

# Check projection code
# Should have `on_agent_observation` method handling TOOL_COMPLETED
```

### Issue: No Token Usage Data

**Debug:**
```bash
# Check stdout events
docker logs <container> | grep token_usage

# Check event store
psql ... -c "SELECT COUNT(*) FROM events WHERE event_type='AgentObservation' AND data->>'observation_type'='TOKEN_USAGE';"
```

### Issue: GitHub App Auth Failed

**Debug:**
```bash
# Verify settings
echo $GH_APP_ID
echo $GH_APP_INSTALLATION_ID
# (Don't echo private key in production!)

# Check container logs
docker logs <container> 2>&1 | grep -i "github\|auth\|token"
```

---

## Cleanup

```bash
# Stop services
just dev-down

# Optional: Clean up test data
just db-reset
```

---

## Notes

- This test should complete in **3-5 minutes**
- Expected cost: **$0.01-0.05** (Claude API usage)
- Requires active internet connection (GitHub API)
- Recommended to run on a test GitHub repository first
