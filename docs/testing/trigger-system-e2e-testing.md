# Local E2E Testing Plan: Trigger System

## Prerequisites

```bash
# 1. Start the dev stack (Docker services + backend)
just dev

# 2. Verify the backend is up
curl http://localhost:8000/
```

> **Note:** The triggers API router is not yet registered in `main.py`. Two options for testing:
> - **Option A**: Use the CLI (`just cli triggers ...`) — works now
> - **Option B**: Use curl against the webhook endpoint — works now
> - The `/api/triggers` REST endpoints require adding `triggers_router` to `main.py` first (see step 0 below)

---

## Step 0 (Optional): Register the triggers router

If you want to test via the REST API at `/api/triggers`:

```python
# In apps/aef-dashboard/src/aef_dashboard/main.py, add:
from aef_dashboard.api import triggers_router
# ...
app.include_router(triggers_router, prefix="/api")
```

---

## Test 1: Register a trigger via CLI

```bash
# Register a self-healing trigger
just cli triggers register \
  --name "ci-self-heal" \
  --event "check_run.completed" \
  --repository "AgentParadise/my-project" \
  --workflow "ci-fix-workflow" \
  --condition "check_run.conclusion eq failure"

# Expected output:
# Trigger registered: tr-XXXXXXXX
#   Name: ci-self-heal
#   Event: check_run.completed
#   Repository: AgentParadise/my-project
#   Workflow: ci-fix-workflow
#   Status: active
```

Save the trigger ID for later steps.

---

## Test 2: Enable a preset via CLI

```bash
just cli triggers enable self-healing \
  --repository "AgentParadise/my-project"

# Expected: preset trigger created with auto-configured conditions
```

---

## Test 3: List and inspect triggers

```bash
# List all triggers
just cli triggers list

# Show details for a specific trigger
just cli triggers show <trigger-id>
```

---

## Test 4: Fire a webhook (simulated CI failure)

Set `AEF_ENVIRONMENT=development` in your `.env` to bypass signature verification, then:

```bash
curl -s -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: check_run" \
  -H "X-GitHub-Delivery: test-delivery-001" \
  -d '{
    "action": "completed",
    "sender": {"login": "human-dev"},
    "repository": {"full_name": "AgentParadise/my-project"},
    "installation": {"id": 12345},
    "check_run": {
      "name": "lint",
      "conclusion": "failure",
      "output": {"title": "Lint failed", "summary": "2 errors"},
      "html_url": "https://github.com/AgentParadise/my-project/runs/1",
      "pull_requests": [
        {"number": 42, "head": {"ref": "feat/test"}}
      ]
    }
  }' | python -m json.tool

# Expected:
# {
#   "status": "triggered",
#   "event": "check_run.completed",
#   "triggers": [
#     {"trigger_id": "tr-XXXX", "execution_id": "exec-XXXXXXXXXXXX"}
#   ]
# }
```

---

## Test 5: Verify fire count incremented

```bash
just cli triggers show <trigger-id>
# Fire Count should now be 1
```

---

## Test 6: Safety guard — bot sender blocked

```bash
curl -s -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: check_run" \
  -H "X-GitHub-Delivery: test-delivery-002" \
  -d '{
    "action": "completed",
    "sender": {"login": "aef-engineer[bot]"},
    "repository": {"full_name": "AgentParadise/my-project"},
    "installation": {"id": 12345},
    "check_run": {
      "conclusion": "failure",
      "pull_requests": [{"number": 42}]
    }
  }' | python -m json.tool

# Expected:
# {"status": "ignored", "event": "check_run.completed", "reason": "No matching triggers"}
```

---

## Test 7: Safety guard — duplicate delivery rejected

```bash
# Re-send same delivery ID from Test 4
curl -s -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: check_run" \
  -H "X-GitHub-Delivery: test-delivery-001" \
  -d '{
    "action": "completed",
    "sender": {"login": "human-dev"},
    "repository": {"full_name": "AgentParadise/my-project"},
    "installation": {"id": 12345},
    "check_run": {
      "conclusion": "failure",
      "pull_requests": [{"number": 42}]
    }
  }' | python -m json.tool

# Expected: "ignored" (duplicate delivery blocked by idempotency guard)
```

---

## Test 8: Pause/resume trigger lifecycle

```bash
# Pause the trigger
just cli triggers pause <trigger-id> --reason "Testing pause"

# Verify it doesn't fire when paused
curl -s -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: check_run" \
  -H "X-GitHub-Delivery: test-delivery-003" \
  -d '{
    "action": "completed",
    "sender": {"login": "human-dev"},
    "repository": {"full_name": "AgentParadise/my-project"},
    "installation": {"id": 12345},
    "check_run": {
      "conclusion": "failure",
      "pull_requests": [{"number": 99}]
    }
  }' | python -m json.tool

# Expected: "ignored" (trigger is paused)

# Resume
just cli triggers resume <trigger-id>

# Now it should fire again
curl -s -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: check_run" \
  -H "X-GitHub-Delivery: test-delivery-004" \
  -d '{
    "action": "completed",
    "sender": {"login": "human-dev"},
    "repository": {"full_name": "AgentParadise/my-project"},
    "installation": {"id": 12345},
    "check_run": {
      "conclusion": "failure",
      "pull_requests": [{"number": 99}]
    }
  }' | python -m json.tool

# Expected: "triggered"
```

---

## Test 9: Conditions not met — no fire

```bash
curl -s -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: check_run" \
  -H "X-GitHub-Delivery: test-delivery-005" \
  -d '{
    "action": "completed",
    "sender": {"login": "human-dev"},
    "repository": {"full_name": "AgentParadise/my-project"},
    "installation": {"id": 12345},
    "check_run": {
      "conclusion": "success",
      "pull_requests": [{"number": 50}]
    }
  }' | python -m json.tool

# Expected: "ignored" (conclusion is "success", not "failure")
```

---

## Test 10: Delete trigger and verify cleanup

```bash
just cli triggers delete <trigger-id>
just cli triggers list
# Trigger should show as deleted or be gone from active list
```

---

## Debugging: Watch dashboard logs

```bash
just dev-logs
# Look for:
#   "Received GitHub webhook: check_run"
#   "Trigger tr-XXXX fired for check_run.completed"
#   "Trigger tr-XXXX blocked by guard: ..."
```
