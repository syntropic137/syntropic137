# Post-Release Validation Runbook

Step-by-step validation of a new Syntropic137 release on a **selfhost stack**.
Run this after every release to catch regressions before users hit them.

> **This runbook validates the published release artifacts (GHCR images, npm CLI
> package) running on the selfhost compose overlay — NOT the local dev stack.**
> The dev stack (`syn-dev-*` images, `just dev`) uses different compose files,
> different port mappings, and no `/api/v1` prefix routing. Results from a dev
> stack do not validate release quality.

Designed to be executed by a developer or by Claude Code following the steps sequentially.

**Estimated time:** 15-30 minutes (read-only validation), 30-60 minutes (with workflow execution and trigger round-trips)

---

## Parallel Execution (Claude Code)

When run by Claude Code, sections can be parallelized via subagents to reduce
wall-clock time from ~30 minutes to ~10 minutes. The dependency graph:

```
Preflight (sequential — verify stack, CLI version, health)
  │
  ├─ Agent A: Sections 3 + 4 — Release artifacts, webhook/polling mode
  ├─ Agent B: Section 5 — Core CLI read-only (all command groups)
  ├─ Agent C: Section 9 — Dashboard UI (browser-qa-agent)
  │   └── All three run in parallel (Batch 1, read-only)
  │
  ├─ Section 6 — Repo & system management (write ops, sequential)
  ├─ Section 7 — Workflow lifecycle (sequential, skip execution if no token budget)
  └─ Section 8 — Trigger lifecycle (sequential, depends on repos + workflows)
      └── Batch 2-3: sequential, uses IDs from Batch 1
```

**Rules for parallel execution:**
- Batch 1 agents are fully independent — launch all three in a single message
- Batch 2-3 must wait for Batch 1 to complete (need discovered IDs)
- Dashboard agent should use `sdlc:browser-qa-agent` subagent type
- Each agent reports `[PASS]`/`[FAIL]`/`[SKIP]` per check
- The orchestrating agent compiles results into the Section 10 report template

---

## Prerequisites

- A **private test repo** with the GitHub App installed (for trigger/event tests)
- `ANTHROPIC_API_KEY` configured (for workflow execution tests — costs real tokens)
- Access to the dashboard at `http://localhost:8137` (or your configured URL)

> **CRITICAL: Test repo policy.**
>
> - This runbook MUST always run against the **selfhost stack** — never the dev stack.
> - **NEVER run trigger or workflow tests against public `syntropic137/*` repos.**
>   Use a private sandbox repo (e.g., `NeuralEmpowerment/sandbox_syn-engineer`).
>   Testing against public repos creates noise in the repo's event history, can
>   trigger real CI workflows, and leaks test activity publicly.
> - The dev stack uses different images, ports, and routing. Validating against dev
>   does not prove the release works for users.

---

## 0. Ensure Selfhost Stack Is Running

Check if the selfhost stack is already up:

```bash
docker ps --format "{{.Image}}\t{{.Names}}" | grep -E "ghcr\.io/syntropic137|syn137-"
```

**If containers are running** with `ghcr.io/syntropic137/` images or `syn137-*` names,
the stack is up — proceed to Section 1.

**If no selfhost containers are found**, start the stack:

```bash
npx @syntropic137/setup init
```

- [ ] Setup completes without errors
- [ ] All services start and report healthy

**If `syn-dev-*` containers are running instead**, you are on the dev stack.
Stop it first, then start the selfhost stack:

```bash
just dev-down
npx @syntropic137/setup init
```

---

## 1. Reset Data and Upgrade Selfhost Stack

> **Start fresh.** Always reset data before a validation run. This ensures
> consistent, reproducible results — no stale sessions, leftover test workflows,
> or duplicate repos from previous runs polluting the validation.

### Reset event store and databases

```bash
npx @syntropic137/setup reset --data
```

If `reset --data` is not available, manually reset:

```bash
docker compose -f docker-compose.syntropic137.yaml down -v
npx @syntropic137/setup init
```

- [ ] All data volumes cleared
- [ ] Stack restarted with clean state
- [ ] `syn sessions list` returns empty
- [ ] `syn workflow list` returns empty
- [ ] `syn repo list` returns empty

### Upgrade to release under test

This step validates that the `npx @syntropic137/setup update` upgrade path works
correctly — this is itself a release quality signal. Users will run this exact
command to pick up new releases.

```bash
npx @syntropic137/setup update
```

- [ ] Update command completes without errors
- [ ] New GHCR images pulled for the release version
- [ ] All containers restart with new images

```bash
npx @syntropic137/setup status
```

- [ ] All services show healthy
- [ ] API responds at health endpoint

Verify the running images match the release version:

```bash
docker ps --format "table {{.Image}}\t{{.Status}}\t{{.Names}}" | grep syn137
```

- [ ] Image tags match the release being validated (e.g., `ghcr.io/syntropic137/syn-api:0.21.6`)
- [ ] All containers show healthy status

```bash
curl -s http://localhost:8137/health | jq .
```

- [ ] Health check returns `ok` / healthy status

---

## 2. Install CLI from npm

> **CRITICAL: Use published artifacts only.** Always install the CLI from npm
> (`@syntropic137/cli`) — never build from source or use `node dist/syn.js`.
> The purpose of this runbook is to validate the **published release artifacts**
> that users will actually use. Building from source validates your local checkout,
> not the release.

```bash
npm install -g @syntropic137/cli@latest
```

- [ ] Install completes without errors

```bash
syn version
```

- [ ] Version matches the release being validated (e.g., `0.21.6`)

```bash
syn health
```

- [ ] API connectivity confirmed
- [ ] No version mismatch warnings

### Verify CLI version matches selfhost stack

The CLI and API must be on the same release version. A mismatch can cause
subtle issues (missing fields, changed endpoints, broken type contracts).

```bash
CLI_VERSION=$(syn version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
API_VERSION=$(docker inspect syn137-api --format '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null | sed 's/^v//')
echo "CLI: $CLI_VERSION  API: $API_VERSION"
[ "$CLI_VERSION" = "$API_VERSION" ] && echo "✅ Versions match" || echo "❌ VERSION MISMATCH"
```

- [ ] CLI version matches API container version

---

## 3. Validate Release Artifacts

### Container images

```bash
docker ps --format "table {{.Image}}\t{{.Status}}\t{{.Names}}" | grep syntropic
```

- [ ] All container image tags match the release version
- [ ] All containers show healthy status

### npm package

```bash
npm info @syntropic137/cli version
```

- [ ] Published version matches the release

### GitHub Release

```bash
gh release view v<VERSION> --repo syntropic137/syntropic137
```

- [ ] Release exists with correct tag
- [ ] Release assets attached (compose file, SHA256SUMS)

---

## 4. Determine Webhook / Polling Mode

Before testing triggers, determine whether the stack is receiving webhooks or
operating in polling-only mode. This affects which triggers can fire.

```bash
syn health
# Check for webhook status in the health response, or:
curl -s http://localhost:8137/health | jq .
```

**If no Cloudflare Tunnel is configured → polling-only mode.**

### Event availability by mode

| Trigger Preset | Event | Polling | Webhook |
|----------------|-------|---------|---------|
| `review-fix` | `pull_request_review.submitted` | Yes | Yes |
| `comment-command` | `issue_comment.created` | Yes | Yes |
| `self-healing` | `check_run.completed` | **No** | Yes |

**Polling-available events (17):** `push`, `pull_request`, `pull_request_review`,
`pull_request_review_comment`, `issue_comment`, `issues`, `create`, `delete`,
`release`, `fork`, `watch`, `commit_comment`, `discussion`, `gollum`, `member`,
`public`, `sponsorship`

**Webhook-only events (CI/CD + security + admin):** `check_run`, `check_suite`,
`workflow_run`, `workflow_job`, `deployment`, `deployment_status`, `status`,
`code_scanning_alert`, `dependabot_alert`, `secret_scanning_alert`,
`branch_protection_rule`, `repository_dispatch`, `workflow_dispatch`, `merge_group`

> Source of truth: `packages/syn-domain/.../github/_shared/event_availability.py`

Mark the appropriate sections below as "skip — requires webhook" when running
in polling-only mode.

---

## 5. Functional Validation — Core CLI (Read-Only)

### Configuration

```bash
syn config show
syn config validate
syn config env
```

- [ ] Configuration displays correctly
- [ ] Validation passes
- [ ] Environment template renders

### Organization hierarchy

```bash
syn org list
syn org show <org-id>
```

- [ ] Orgs listed without errors

### System management

```bash
syn system list
syn system show <system-id>
syn system status <system-id>
syn system cost <system-id>
syn system activity <system-id>
syn system patterns <system-id>
syn system history <system-id>
```

- [ ] Systems listed
- [ ] System status shows health info
- [ ] Cost breakdown renders (may be zero on fresh stack)
- [ ] Activity shows recent executions (may be empty)
- [ ] Patterns shows failure analysis (may be empty)
- [ ] History shows execution history with status filtering

### Repositories

```bash
syn repo list
syn repo show <repo-id>
syn repo health <repo-id>
syn repo cost <repo-id>
syn repo activity <repo-id>
syn repo failures <repo-id>
syn repo sessions <repo-id>
```

- [ ] Connected repos listed (requires GitHub App installation)
- [ ] Repo detail shows metadata and system assignment
- [ ] Repo health data renders
- [ ] Repo cost breakdown loads
- [ ] Repo activity shows recent executions
- [ ] Repo failures lists recent failures (may be empty)
- [ ] Repo sessions lists agent sessions for the repo

### Workflows

```bash
syn workflow list
syn workflow show <workflow-id>
syn workflow search
syn workflow installed
```

- [ ] Existing workflows appear
- [ ] No deserialization or schema errors
- [ ] Marketplace search returns results (if marketplace registered)
- [ ] Installed packages listed

### Marketplace

```bash
syn marketplace list
syn marketplace refresh
```

- [ ] Registered marketplaces listed
- [ ] Refresh completes without errors

### Triggers

```bash
syn triggers list
syn triggers list --all
syn triggers show <trigger-id>
syn triggers history <trigger-id>
```

- [ ] Trigger rules listed with safety guards (max_fires, cooldown, budget)
- [ ] `--all` flag shows triggers across all repos
- [ ] Trigger detail shows event type and conditions
- [ ] Trigger history shows past firings

### Sessions

```bash
syn sessions list
syn sessions show <session-id>
```

- [ ] Historical sessions appear (if any exist)
- [ ] Session detail shows tool timeline, tokens, cost

### Conversations

```bash
syn conversations show <session-id>
syn conversations metadata <session-id>
```

- [ ] Conversation log lines render
- [ ] Metadata summary shows model, tokens, duration

### Events

```bash
syn events recent
syn events session <session-id>
syn events timeline <session-id>
syn events costs <session-id>
syn events tools <session-id>
```

- [ ] Recent events load across sessions
- [ ] Per-session timeline, costs, and tools render

### Observe

```bash
syn observe tools <session-id>
syn observe tokens <session-id>
```

- [ ] Tool execution timeline renders
- [ ] Token breakdown renders

### Insights

```bash
syn insights overview
syn insights cost
syn insights heatmap
```

- [ ] Global overview loads
- [ ] Cost breakdown renders
- [ ] Heatmap shows activity over time

### Costs

```bash
syn costs summary
syn costs sessions
syn costs session <session-id>
syn costs executions
syn costs execution <execution-id>
```

- [ ] Aggregated cost summary renders
- [ ] Per-session cost breakdown loads
- [ ] Per-execution cost breakdown loads

### Metrics

```bash
syn metrics show
```

- [ ] Aggregated workflow and session metrics render

### Artifacts

```bash
syn artifacts list
syn artifacts show <artifact-id>
syn artifacts content <artifact-id>
```

- [ ] Artifact listing works (may be empty on fresh stack)
- [ ] Artifact detail and content render (if artifacts exist)

---

## 6. Functional Validation — Repo & System Management (Write Operations)

### Register a repository

```bash
syn repo register --url owner/repo
```

- [ ] Repo registered successfully
- [ ] Appears in `syn repo list`

### Assign repo to system

```bash
syn repo assign <repo-id> --system <system-id>
```

- [ ] Assignment succeeds
- [ ] `syn repo show <repo-id>` shows system assignment
- [ ] `syn system show <system-id>` includes the repo

### Unassign repo

```bash
syn repo unassign <repo-id>
```

- [ ] Unassignment succeeds
- [ ] Repo no longer associated with system

---

## 7. Functional Validation — Workflow Lifecycle

> **COST WARNING: This section runs real workflows that consume Anthropic API tokens.**
>
> Running workflow executions is mandatory for a complete validation — without it,
> the core product loop (workflow → agent → observability) is untested. However,
> it costs real money.
>
> **Minimum validation:** Run at least 2 different workflows to completion and verify
> session data, cost tracking, and observability pipeline end-to-end.
>
> **If run by Claude Code:** Before executing workflows, pause and confirm with the
> developer:
>
> *"I'm at the workflow execution stage of the post-release validation. I need to
> run at least 2 workflows to validate the execution → session → observability
> pipeline. This will consume Anthropic API tokens. Do you want me to proceed?"*
>
> Do NOT run workflows without explicit developer approval.

### Validate a workflow definition

```bash
syn workflow validate <path-to-workflow.yaml>
```

- [ ] Validation passes for a valid workflow file
- [ ] Reports errors for malformed files

### Install a workflow

```bash
syn workflow search
syn workflow info <plugin-name>
syn workflow install <plugin-name>
```

- [ ] Marketplace search returns results
- [ ] Plugin info shows details (phases, model, description)
- [ ] Workflow installed successfully
- [ ] `syn workflow list` shows the new workflow
- [ ] `syn workflow installed` shows the package

### Run a workflow (costs tokens)

```bash
syn workflow run <workflow-id>
```

- [ ] Execution starts
- [ ] Workspace provisioned (container created)

### Monitor execution

```bash
syn execution list
syn execution show <execution-id>
syn execution list --status running
syn control status <execution-id>
```

- [ ] Execution appears in list
- [ ] Status filtering works
- [ ] Status updates as phases progress

### Live streaming

```bash
syn watch execution <execution-id>
syn watch activity
```

- [ ] SSE events stream in real time
- [ ] Activity feed shows global events

### Execution control

```bash
syn control pause <execution-id>
syn control resume <execution-id>
# or to stop:
syn control cancel <execution-id>
syn control stop <execution-id>
```

- [ ] Pause/resume works (if execution supports yield points)
- [ ] Cancel stops the execution cleanly
- [ ] Stop sends SIGINT for immediate halt

### Verify session recorded

```bash
syn sessions list
syn sessions show <session-id>
syn costs session <session-id>
syn events timeline <session-id>
```

- [ ] New session appears for the execution
- [ ] Token usage and cost recorded
- [ ] Tool executions captured in timeline

### Verify artifacts

```bash
syn artifacts list
syn artifacts show <artifact-id>
syn artifacts content <artifact-id>
```

- [ ] Artifacts collected from execution (if workflow produces any)
- [ ] Content is retrievable

### Update workflow package

```bash
syn workflow update <package-name> --dry-run
syn workflow update <package-name>
```

- [ ] Dry run shows what would change
- [ ] Update pulls latest version

### Export workflow

```bash
syn workflow export <workflow-id> --format plugin
```

- [ ] Export produces a Claude Code plugin package

### Clean up

```bash
syn workflow delete <workflow-id>
syn workflow uninstall <package-name>
```

- [ ] Workflow archived (soft-deleted)
- [ ] Package uninstalled
- [ ] `syn workflow list` no longer shows it (unless `--all` flag)

---

## 8. Functional Validation — Trigger Lifecycle & Round-Trip

### Determine available trigger presets

Based on Section 4 (webhook/polling mode):

| Preset | Can test? |
|--------|-----------|
| `review-fix` | Yes (polling-supported) |
| `comment-command` | Yes (polling-supported) |
| `self-healing` | Only with webhook/tunnel |

### Register triggers with safety limits

```bash
# Enable a polling-compatible preset
syn triggers enable review-fix --repo owner/repo --workflow <workflow-id>

# Register a custom trigger with safety limits
syn triggers register \
  --event issue_comment \
  --action created \
  --repo owner/repo \
  --workflow <workflow-id> \
  --max-fires 5 \
  --cooldown 300 \
  --budget 1.00
```

- [ ] Preset enabled successfully
- [ ] Custom trigger registered with safety limits
- [ ] `syn triggers list` shows both triggers
- [ ] `syn triggers show <trigger-id>` shows conditions and safety guards

### Trigger pause/resume

```bash
syn triggers pause <trigger-id>
syn triggers show <trigger-id>
syn triggers resume <trigger-id>
```

- [ ] Trigger paused — shows paused status
- [ ] Trigger resumed — shows active status

### Polling-based round-trip: PR review → trigger → execution

> **COST WARNING: Trigger round-trips fire real workflow executions.**
>
> This validates the most critical loop in the product: GitHub event → event
> pipeline → trigger evaluation → workflow execution → observability. At least
> one trigger round-trip must succeed for the release to be considered validated.
>
> **If run by Claude Code:** Confirm with the developer before proceeding:
>
> *"I'm at the trigger round-trip stage. I'll set up a trigger, create a GitHub
> event to fire it, and verify the full loop completes. This will consume API
> tokens for the triggered workflow execution. Proceed?"*

This validates the full loop: GitHub event → Events API polling → event pipeline → dedup → trigger evaluation → workflow execution.

1. **Ensure a `review-fix` trigger is active** (from above)

2. **Create a PR** on the connected repo (or use an existing one)

3. **Submit a review** (e.g., "Request changes" with a comment describing an issue)

4. **Wait 60-90 seconds** (active polling interval)

5. **Verify event ingested and trigger fired:**

```bash
syn events recent
syn triggers history <trigger-id>
```

- [ ] PR review event picked up via polling
- [ ] Trigger fired in response to the review
- [ ] Correct workflow associated with the trigger
- [ ] Execution started for the triggered workflow
- [ ] No duplicate triggers (dedup working — verify with a second poll cycle)

6. **Monitor the triggered execution:**

```bash
syn execution list
syn execution show <execution-id>
syn sessions show <session-id>
```

- [ ] Execution completes or can be cancelled
- [ ] Session recorded with correct repo context

### Polling-based round-trip: comment command → trigger → execution

1. **Ensure a `comment-command` trigger is active**

```bash
syn triggers enable comment-command --repo owner/repo --workflow <workflow-id>
```

2. **Post a comment** on a PR or issue: `/syn run`

3. **Wait 60-90 seconds**

4. **Verify:**

```bash
syn events recent
syn triggers history <trigger-id>
```

- [ ] Comment event picked up via polling
- [ ] Trigger fired on `/syn` prefix match
- [ ] Execution started

### Webhook-based round-trip: self-healing (requires tunnel)

> **Skip if no Cloudflare Tunnel is configured.** The `self-healing` preset uses
> `check_run.completed` which is webhook-only — not available via the Events API.

1. **Ensure tunnel is active** (check Cloudflare Zero Trust dashboard)

2. **Enable self-healing:**

```bash
syn triggers enable self-healing --repo owner/repo --workflow <workflow-id>
```

3. **Push a commit that fails CI** (e.g., introduce a lint error)

4. **Verify (should fire within seconds, not polling interval):**

```bash
syn triggers history <trigger-id>
```

- [ ] Webhook delivered (check GitHub App Advanced tab)
- [ ] Trigger fires in real-time
- [ ] Self-healing execution starts
- [ ] Poller mode is `SAFETY_NET` (webhooks healthy)

### Trigger safety guards validation

```bash
# Check that safety limits are enforced:
syn triggers show <trigger-id>
```

- [ ] `max_fires` — trigger stops firing after limit reached
- [ ] `cooldown` — trigger respects cooldown period between fires
- [ ] `budget` — trigger respects cost budget cap

### Trigger cleanup

```bash
syn triggers delete <trigger-id>
syn triggers disable-all --repo owner/repo
```

- [ ] Individual trigger deleted
- [ ] All triggers for repo disabled

---

## 9. Functional Validation — Dashboard (Playwright)

> **Use Playwright for automated dashboard validation.** When run by Claude Code,
> use the `sdlc:browser-qa-agent` subagent type with Playwright MCP tools to
> validate the dashboard programmatically. This ensures repeatable, scriptable
> UI validation rather than manual browser checks.

Open `http://localhost:8137` via Playwright.

### Navigation and rendering

- [ ] Dashboard loads without errors
- [ ] All navigation links work (workflows, sessions, executions, triggers, insights)

### Data views

- [ ] Session list renders with data
- [ ] Session detail view shows tool timeline and token breakdown
- [ ] Execution detail view loads with phase progression
- [ ] Trigger history visible and matches CLI output
- [ ] Cost/token metrics display correctly

### Real-time

- [ ] WebSocket connection established
- [ ] Live updates appear when new events are recorded

### Insights

- [ ] Overview page loads with system health
- [ ] Cost breakdown page renders
- [ ] Heatmap shows activity over time

---

## 10. Validation Report

Copy and fill in after completing the runbook.

```
## Post-Release Validation Report

**Release version:** v_.__._
**Date:** YYYY-MM-DD
**Validated by:** <name or agent>
**Stack environment:** selfhost / dev
**Webhook mode:** polling-only / webhook active

### Summary

| Area                     | Status              |
|--------------------------|---------------------|
| Stack update             | pass / fail         |
| CLI update               | pass / fail         |
| Release artifacts        | pass / fail         |
| Core CLI (read-only)     | pass / fail         |
| Repo/system management   | pass / fail         |
| Workflow lifecycle        | pass / fail / skip  |
| Trigger round-trip (poll)| pass / fail / skip  |
| Trigger round-trip (wh)  | pass / fail / skip  |
| Dashboard UI             | pass / fail         |

### Feature Matrix

| Command / Feature                  | Status | Notes |
|------------------------------------|--------|-------|
| **Stack & CLI**                    |        |       |
| syn version                        |        |       |
| syn health                         |        |       |
| syn config show/validate/env       |        |       |
| **Organization**                   |        |       |
| syn org list/show                  |        |       |
| syn system list/show/status        |        |       |
| syn system cost/activity/patterns  |        |       |
| syn system history                 |        |       |
| **Repositories**                   |        |       |
| syn repo list/show/health          |        |       |
| syn repo register                  |        |       |
| syn repo assign/unassign           |        |       |
| syn repo cost/activity/failures    |        |       |
| syn repo sessions                  |        |       |
| **Workflows**                      |        |       |
| syn workflow list/show/search      |        |       |
| syn workflow validate              |        |       |
| syn workflow install/installed     |        |       |
| syn workflow run                   |        |       |
| syn workflow update (--dry-run)    |        |       |
| syn workflow export                |        |       |
| syn workflow delete/uninstall      |        |       |
| syn workflow info/init             |        |       |
| **Marketplace**                    |        |       |
| syn marketplace list/refresh       |        |       |
| syn marketplace add/remove         |        |       |
| **Executions**                     |        |       |
| syn execution list/show            |        |       |
| syn execution list --status        |        |       |
| syn control status/pause/resume    |        |       |
| syn control cancel/stop/inject     |        |       |
| syn watch execution/activity       |        |       |
| **Sessions & Observability**       |        |       |
| syn sessions list/show             |        |       |
| syn conversations show/metadata    |        |       |
| syn events recent/session          |        |       |
| syn events timeline/costs/tools    |        |       |
| syn observe tools/tokens           |        |       |
| **Insights & Costs**               |        |       |
| syn insights overview/cost/heatmap |        |       |
| syn costs summary/sessions/session |        |       |
| syn costs executions/execution     |        |       |
| syn metrics show                   |        |       |
| **Artifacts**                      |        |       |
| syn artifacts list/show/content    |        |       |
| syn artifacts create               |        |       |
| **Triggers**                       |        |       |
| syn triggers list/show/history     |        |       |
| syn triggers enable (review-fix)   |        |       |
| syn triggers enable (comment-cmd)  |        |       |
| syn triggers enable (self-healing) |        | webhook-only |
| syn triggers register (custom)     |        |       |
| syn triggers pause/resume          |        |       |
| syn triggers delete/disable-all    |        |       |
| Trigger safety guards              |        |       |
| **Event Pipeline**                 |        |       |
| Polling event ingestion            |        |       |
| Trigger round-trip (PR review)     |        |       |
| Trigger round-trip (comment cmd)   |        |       |
| Webhook event ingestion            |        | requires tunnel |
| Dedup (no duplicate triggers)      |        |       |
| **Dashboard**                      |        |       |
| Dashboard loads                    |        |       |
| Dashboard navigation               |        |       |
| Session/execution detail views     |        |       |
| Real-time updates (WebSocket)      |        |       |
| Insights pages                     |        |       |

### Issues Found

| Severity | Description | Repro steps | Issue # |
|----------|-------------|-------------|---------|
|          |             |             |         |

### Gaps / Friction

Items that work but could be smoother for launch readiness:

-

### Change Failures (Bugs)

Regressions from the release that need immediate attention:

-

### Performance / Reliability Notes

-
```
