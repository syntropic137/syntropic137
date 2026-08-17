# Post-Release Validation Runbook

Step-by-step validation of a new Syntropic137 release on a **selfhost stack**.
Run this after every release to catch regressions before users hit them.

> **This runbook validates the published release artifacts (GHCR images, npm CLI
> package) running on the selfhost compose project (`syntropic137_selfhost`).**
>
> **The selfhost stack and dev stack are completely separate.** Do not confuse them:
>
> | | Selfhost (validate this) | Dev (ignore for validation) |
> |---|---|---|
> | **Compose project** | `syntropic137_selfhost` | `syn-dev` |
> | **Container prefix** | `syn137-*` | `syn-dev-*` |
> | **API port** | `8137` | `8000` (or configured dev port) |
> | **Images** | `ghcr.io/syntropic137/*:<VERSION>` | `syntropic137_development-*:latest` (locally built) |
> | **Config location** | `~/.syntropic137/` | `docker/docker-compose.*.yaml` in repo |
> | **Compose file** | `~/.syntropic137/docker-compose.syntropic137.yaml` | `docker/docker-compose.yaml` |
>
> They can run side by side without collision. **Results from the dev stack do not
> validate release quality** - dev images are locally built and may contain uncommitted
> changes.

Designed to be executed by a developer or by Claude Code following the steps sequentially.

**Estimated time:** 15-30 minutes (read-only validation), 30-60 minutes (with workflow execution and trigger round-trips)

---

## Validation Modes

This runbook supports two modes. **Pick one before you start** - they differ in what
they prove and which stack they target.

| | **Post-release** (default) | **Pre-release** |
|---|---|---|
| **Question answered** | "Did the published release work for users?" | "Is `main` safe to cut a release from?" |
| **Runs after** | A release publishes | Before a version bump / release PR |
| **Images** | Published `ghcr.io/syntropic137/*` digests | Built locally from the working tree |
| **Stack** | Selfhost (`syntropic137_selfhost`, port 8137) | On-demand env (ADR-060), port `<slot>8137` |
| **Setup** | `npx @syntropic137/setup update` (§0) | `just env-up <branch>` (§0-PRE) |
| **Sections** | All | All except §2 (release artifacts) |

> **Why pre-release mode exists.** `npx @syntropic137/setup update` always pulls the
> *last published* GHCR digests. On a `main` that is N commits ahead of the last tag,
> that validates the previous release, not the code you are about to ship. Pre-release
> mode builds from the working tree instead.

> **Do not use the selfhost overlay for pre-release validation.** It hardcodes
> `syn137-*` container names, the fixed `syn137_*` volumes, and port 8137, so it
> cannot run beside a live selfhost stack - using it means destroying the user's
> running deployment (and its data, since the repo and installed DB secrets differ).
> The on-demand environment system is isolated by design: per-env container names,
> per-env volumes, and ports offset by slot × 10000.

### §0-PRE. Stand up a pre-release stack

```bash
cd <repo root>
just env-list                    # see existing envs and free slots
just env-down main               # recycle a stale env of the same name (safe: ephemeral)
just env-up main                 # allocates a slot, builds from the working tree, starts
just env-status main             # prints the allocated ports
```

- [ ] Environment allocated a slot and reports its URLs
- [ ] All `syn-env-<name>-*` containers healthy
- [ ] The live selfhost stack on 8137 (if any) is **still running and untouched**

Point the CLI at the on-demand env for every subsequent section:

```bash
export SYN_API_URL="http://localhost:<gateway-port>/api/v1"
syn health
```

- [ ] `syn health` reports healthy against the on-demand env

> **Record the working-tree state.** Pre-release mode validates the working tree, not
> necessarily clean `main`. Capture `git status --short` and `git rev-parse HEAD` in
> the report so results are attributable.

### Gate integrity check (pre-release only)

Local gates can silently stop gating. Before trusting a green CI run, confirm the
tools CI runs are the tools the repo pins.

```bash
just fitness-check
just typecheck
just docs-sync
just vsa-validate
vsa --version    # MUST match lib/event-sourcing-platform/vsa workspace version
```

- [ ] `vsa --version` matches the pinned submodule version, **locally and in CI**
- [ ] All gates pass, or every failure is triaged in the report

> **Known trap.** `.github/actions/setup-vsa` installs only `if ! command -v vsa`, and
> its cache `restore-keys` is a loose prefix. A cached older `vsa` binary is restored,
> the guard short-circuits, and the pinned version never installs - so CI can report
> success while running a years-old validator. Always compare the version CI *printed*
> against the pinned one, not just the step's conclusion.

---

## Parallel Execution (Claude Code)

When run by Claude Code, sections can be parallelized via subagents to reduce
wall-clock time from ~30 minutes to ~10 minutes. The dependency graph:

```
Preflight (sequential - reset stack, install CLI, verify health)
  │
  ├─ Agent A: Sections 2 + 3 - Release artifacts, webhook/polling mode
  ├─ Agent B: Section 4 - Core CLI read-only (all command groups)
  ├─ Agent C: Section 8 - Dashboard UI (browser-qa-agent)
  │   └── All three run in parallel (Batch 1, read-only)
  │
  ├─ Section 5 - Repo & system management (write ops, sequential)
  ├─ Section 6 - Workflow lifecycle (sequential, skip execution if no token budget)
  └─ Section 7 - Trigger lifecycle (sequential, depends on repos + workflows)
      └── Batch 2-3: sequential, uses IDs from Batch 1
```

**Rules for parallel execution:**
- Batch 1 agents are fully independent - launch all three in a single message
- Batch 2-3 must wait for Batch 1 to complete (need discovered IDs)
- Dashboard agent should use `sdlc:browser-qa-agent` subagent type
- Each agent reports `[PASS]`/`[FAIL]`/`[SKIP]` per check
- The orchestrating agent compiles results into the Section 9 report template

---

## Prerequisites

- A **private test repo** with the GitHub App installed (for trigger/event tests)
- `ANTHROPIC_API_KEY` configured (for workflow execution tests - costs real tokens)
- Access to the dashboard at `http://localhost:8137` (or your configured URL)

> **CRITICAL: Test repo policy.**
>
> - This runbook MUST always run against the **selfhost stack** - never the dev stack.
> - **NEVER run trigger or workflow tests against public `syntropic137/*` repos.**
>   Use a private sandbox repo (e.g., `NeuralEmpowerment/sandbox_syn-engineer`).
>   Testing against public repos creates noise in the repo's event history, can
>   trigger real CI workflows, and leaks test activity publicly.
> - The dev stack uses different images, ports, and routing. Validating against dev
>   does not prove the release works for users.

---

## 0. Reset and Upgrade Selfhost Stack

> **MANDATORY before every validation run.** Don't bother checking what's
> currently running - tear it down, upgrade, and verify. This ensures clean
> state, correct GHCR images, and reproducible results every time.
>
> `npx @syntropic137/setup update` is the single command that pulls the
> correct GHCR images for the release and starts the stack. This is the same
> upgrade path users follow, so it's itself a release quality signal.

### Step 1: Tear down and clear data

```bash
docker compose -f ~/.syntropic137/docker-compose.syntropic137.yaml down -v
```

- [ ] Selfhost stack stopped and all data volumes removed

> **If no selfhost stack exists yet**, initialize instead:
> ```bash
> npx @syntropic137/setup init
> ```

### Step 2: Upgrade to the release under test

```bash
npx @syntropic137/setup update
```

- [ ] Update command completes without errors
- [ ] New GHCR images pulled for the release version
- [ ] All containers start with new images

> **If the update fails:** Re-initialize from scratch:
> ```bash
> docker compose -f ~/.syntropic137/docker-compose.syntropic137.yaml down -v
> npx @syntropic137/setup init
> ```

### Step 3: Verify GHCR images and health

```bash
docker ps --format "table {{.Image}}\t{{.Status}}\t{{.Names}}" | grep syn137
```

- [ ] Images are `ghcr.io/syntropic137/*` (GHCR digests) - **not** `syntropic137_development-*:latest`
- [ ] All containers show healthy status

```bash
curl -s http://localhost:8137/health
```

- [ ] Health check returns healthy status

> **Troubleshooting:** If you see `syntropic137_development-*:latest` images,
> the stack is running locally-built dev images instead of published GHCR images.
> This means the update didn't work correctly - tear down and re-initialize.

### Step 4: Verify clean state

```bash
syn sessions list
syn workflow list
syn repo list
```

- [ ] Sessions list is empty
- [ ] Workflow list is empty
- [ ] Repo list is empty

> **Note:** `syn workflow packages` reads local CLI history (`~/.syntropic137/workflows/installed.json`),
> not the stack. Clear it before a clean-slate validation:
> ```bash
> rm -f ~/.syntropic137/workflows/installed.json
> ```

### Step 5: Pre-flight GitHub App installation check

Before §6/§7 (which need a real repo to run workflows and fire triggers against),
confirm the GitHub App is installed on your test repo. Skipping this means
register → assign → run fails multiple minutes in with a cryptic message.

```bash
# Replace owner/repo with your test repo
TEST_REPO="owner/repo"
APP_NAME=$(grep SYN_GITHUB_APP_NAME ~/.syntropic137/.env | cut -d= -f2)
echo "Checking GitHub App '$APP_NAME' installation on $TEST_REPO..."
gh api "/repos/$TEST_REPO/installation" --jq '.id' 2>&1 | head -1
```

- [ ] Response is a numeric installation ID (not an error)
- [ ] If 404: install the App on the repo via `https://github.com/apps/$APP_NAME` before proceeding

---

## 1. Install CLI from npm

> **CRITICAL: Use published artifacts only.** Always install the CLI from npm
> (`@syntropic137/cli`) - never build from source or use `node dist/syn.js`.
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

- [ ] Version matches the release being validated (e.g., `<VERSION>`)

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

## 2. Validate Release Artifacts

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

## 3. Determine Webhook / Polling Mode

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

Mark the appropriate sections below as "skip - requires webhook" when running
in polling-only mode.

---

## 4. Functional Validation - Core CLI (Read-Only)

> **Fresh stack note:** After a data reset (Section 0), most commands that take
> `<id>` arguments will have no data. For these commands, verify they return
> graceful empty responses (empty lists, "not found" errors) without crashes or
> stack traces. Re-run ID-dependent commands after Sections 5-6 create data.

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
syn workflow packages
```

- [ ] Existing workflows appear
- [ ] No deserialization or schema errors
- [ ] Marketplace search returns results (if marketplace registered)
- [ ] Local package history listed (`syn workflow packages` shows marketplace pulls on this machine)

### Marketplace

```bash
syn marketplace list
syn marketplace refresh
```

- [ ] Registered marketplaces listed (should show `syntropic137-marketplace`)
- [ ] Refresh completes without errors

If no marketplace is registered:

```bash
syn marketplace add syntropic137/syntropic137-marketplace
```

- [ ] Marketplace added successfully
- [ ] Appears in `syn marketplace list`

To test removal and re-add (round-trip):

```bash
syn marketplace remove syntropic137-marketplace
syn marketplace list
syn marketplace add syntropic137/syntropic137-marketplace
```

- [ ] Remove succeeds
- [ ] List confirms removal
- [ ] Re-add succeeds

### Triggers

```bash
syn triggers list
syn triggers list --all
syn triggers show <trigger-id>
syn triggers history <trigger-id>
```

- [ ] Trigger rules listed with safety guards (`max_attempts`, `cooldown`)
- [ ] `--all` flag includes **deleted** triggers (cross-repo listing is the default;
      `--repo` narrows it)
- [ ] `--status active|paused|deleted` filters correctly
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
- [ ] `cost_by_model` is populated (not `{}`) on session and execution cost responses

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

> **Note:** `syn artifacts create` is tested in Section 6 ("Create an artifact
> manually"), after a workflow execution has produced artifacts to list alongside.

---

## 5. Functional Validation - Repo & System Management (Write Operations)

### Register a repository

```bash
syn repo register --url owner/repo
```

- [ ] Repo registered successfully
- [ ] Appears in `syn repo list`

### Create an org and system (required for assignment)

> **Fresh stack note:** `syn repo assign` requires an existing system. On a fresh
> stack, create them first. `syn system create` requires `--org`.

```bash
ORG_ID=$(syn org create --name "Test Org" --slug "test-org" 2>&1 | grep -oE 'org-[a-f0-9]+')
echo "Org: $ORG_ID"
syn system create --name "test-system" --org "$ORG_ID"
```

- [ ] Org created successfully
- [ ] System created with org reference

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

## 6. Functional Validation - Workflow Lifecycle

> **COST WARNING: This section runs real workflows that consume Anthropic API tokens.**
>
> Running workflow executions is mandatory for a complete validation - without it,
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

### Marketplace → Install → Running Stack (critical onboarding path)

> **This is the primary onboarding flow for new users.** A user's first experience
> is: search the marketplace, pick a workflow, install it, run it. If any step in
> this chain has friction, the onboarding story fails. Test this from a clean state
> (no workflows on the stack) to validate the real first-run experience.

**Clean slate** - delete existing workflows first (if any):

```bash
syn workflow list
syn workflow delete <id> --force  # for each existing workflow
```

- [ ] Stack has no workflows before starting

**Search the marketplace:**

```bash
syn workflow search
```

- [ ] Returns plugins from the registered marketplace
- [ ] Output includes name, version, category, description, registry source
- [ ] Helpful install prompt shown (e.g., "Install with: syn workflow install <name>")

**Inspect a plugin before installing:**

```bash
syn workflow info code-review
syn workflow info sdlc-trunk
```

- [ ] Shows version, description, category, tags
- [ ] Shows source (marketplace repo + path)
- [ ] Shows install command

**Install plugins from marketplace to the running stack:**

```bash
syn workflow install code-review
syn workflow install sdlc-trunk
```

- [ ] Each install clones the marketplace repo, parses plugin, creates workflow(s)
- [ ] `code-review` installs 1 workflow (2 phases)
- [ ] `sdlc-trunk` installs 3 workflows (9 phases total)
- [ ] Each workflow gets a unique ID assigned by the API

**Verify workflows are on the running stack:**

```bash
syn workflow list
syn workflow show <workflow-id>
```

- [ ] All installed workflows appear in list
- [ ] Workflow detail shows correct phases, type, classification
- [ ] `syn workflow packages` shows the local marketplace-pull history with version and source

### Run a workflow (costs tokens)

```bash
syn workflow run <workflow-id>
```

- [ ] Execution starts
- [ ] Workspace provisioned (container created)

> **Repositories (v0.25.2+):** Pass repos as a typed channel with `-R`, not through `--input`.
> `-R` is repeatable and accepts three forms: `owner/repo`, a full GitHub URL,
> or a `repo-*` ID from `syn repo list`. Example: `syn workflow run <id> -R owner/a -R repo-abc123`.
>
> `--input repository=owner/repo` and `--input repos=owner/a,owner/b` are rejected
> at the CLI (and at the API as a belt-and-suspenders 422). The error message points
> you at `-R`. Older workflows that declared `repository` in `input_declarations` must
> drop it and rely on execution-time `-R` values.

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

### Inject context into running execution

```bash
syn control inject <execution-id> --message "Focus on the auth module"
```

- [ ] Injection accepted (or graceful error if execution not in injectable state)

### Verify session recorded

```bash
syn sessions list
syn sessions show <session-id>
syn costs session <session-id>
syn events timeline <session-id>
```

- [ ] New session appears for the execution
- [ ] Token usage and cost recorded
- [ ] `cost_by_model` populated with model name and cost (e.g., `{"sonnet": "0.35"}`)
- [ ] Tool executions captured in timeline

### Verify artifacts

```bash
syn artifacts list
syn artifacts show <artifact-id>
syn artifacts content <artifact-id>
```

- [ ] Artifacts collected from execution (if workflow produces any)
- [ ] Content is retrievable
- [ ] **Only real outputs are collected** - no `.pytest_cache/`, `__pycache__/`, `.git/`
      or other build/cache directories appear in the list
- [ ] Binary files are not classified as `type: text`

> A workflow whose agent runs tests will surface this immediately: as of v0.25.4 a run
> producing 3 real outputs collected 9 artifacts, 6 of them cache junk including binary
> `.pyc` files typed as `text`.

### Create an artifact manually

```bash
echo "validation probe" > /tmp/syn-probe.txt
syn artifacts create --file /tmp/syn-probe.txt --type report
syn artifacts list
syn artifacts show <artifact-id>
syn artifacts content <artifact-id>
```

- [ ] Artifact created and assigned an ID
- [ ] Appears in `syn artifacts list`
- [ ] `content` returns the uploaded bytes
- [ ] `syn artifacts show <id> --no-content` omits the body

### Update workflow package

```bash
syn workflow update <package-name> --dry-run
syn workflow update <package-name>
```

- [ ] Dry run shows what would change
- [ ] Update pulls latest version

### Initialize a new workflow from template

> `init` takes an optional `<directory>` positional and scaffolds into it (defaulting
> to the **current** directory). `--name` sets the workflow name inside the YAML; it
> does NOT create a directory. `--type` is a free-form label (default `custom`);
> package shape is selected by the separate `--multi` boolean.

```bash
syn workflow init ./test-workflow --name test-workflow
syn workflow validate ./test-workflow
```

- [ ] Scaffolds a new workflow YAML file into `./test-workflow/`
- [ ] Generated file passes `syn workflow validate`

Multi-workflow package variant:

```bash
syn workflow init ./test-package --name test-package --multi --phases 3
syn workflow validate ./test-package
```

- [ ] `--multi` scaffolds a multi-workflow package
- [ ] `--phases` controls generated phase count

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
- [ ] `syn workflow list` no longer shows it (archived workflows are filtered from default list)

---

## 6.1 Functional Validation - Agent Providers & Codex Harness

> Added for the codex bridge (#779), opt-in codex/claude delegation (#785), per-phase
> provider selection (#786), and codex transcript rendering (#791).

A phase selects its harness with a per-phase `agent:` block:

```yaml
phases:
  - id: implement
    agent:
      provider: claude | claude-interactive | codex
      agent_id: claude | codex | gemini     # only meaningful for claude-interactive
      model: <model-id>                     # ignored for codex
      allow_delegation: false
```

Canonical enum: `AgentProvider` in
`packages/syn-shared/src/syn_shared/agents.py`.

### Preconditions (codex)

Codex authenticates with a **file-injected `~/.codex/auth.json`** (ChatGPT
subscription), never an API key in argv or env.

```bash
# 1. Stage the credential (reads ~/.codex/auth.json, honours CODEX_HOME)
just codex-auth-clip --dotenv        # writes CODEX_AUTH_JSON= into .env

# 2. The workspace image MUST contain the codex binary
docker run --rm "${SYN_WORKSPACE_DOCKER_IMAGE:-ghcr.io/agentparadise/agentic-workspace-claude-cli:latest}" codex --version

# 3. Codex needs egress to api.openai.com (the Envoy sidecar is Anthropic-only and
#    is skipped for codex phases, so codex requires direct/allowlisted egress)
```

- [ ] `CODEX_AUTH_JSON` is set on the stack **and parses as a JSON object**
- [ ] `codex --version` succeeds inside the workspace image
- [ ] `api.openai.com` is reachable from the agent network

> **Presence is not enough.** A mangled credential looks identical to a good one
> at the `[ -n "$CODEX_AUTH_JSON" ]` level, and then fails deep inside workspace
> provisioning with nothing naming the secret. Assert that it *parses*:
>
> ```bash
> docker exec <api-container> python3 -c \
>   "import json,os; d=json.loads(os.environ['CODEX_AUTH_JSON']); \
>    print('auth_mode=', d.get('auth_mode'), 'keys=', len(d))"
> ```
>
> Since ADR-067 the settings layer validates this at load, so a bad value fails
> fast with a named error - but check it explicitly here, because the whole
> point of this section is that codex works on a real deployment.

> **Verify the PRODUCTION resolution path, not a hand-staged `.env`.** The
> credential should arrive via 1Password -> `scripts/op_env_export.py` ->
> container, which is what a real deployment does. A value pasted into the root
> `.env` for convenience proves only that the container can read an env var.
>
> **Inspect secrets with `op item get ... --format json`, never `--fields
> --reveal`**: the `--fields` output CSV-quotes values containing quotes and
> commas, which reads exactly like a corrupted credential and has already caused
> one false diagnosis.

> **Blocker if any fail.** A codex phase with no credential, no binary, or no egress
> fails at provisioning or produces a broken stream.

### Run a codex workflow (costs tokens)

Two example workflows ship in `workflows/examples/` and are seeded by `just dev` /
`just selfhost-seed`:

| File | What it proves |
|---|---|
| `codex-demo.yaml` | Single codex phase, no repo required. The primary probe. |
| `codex-delegates-to-claude.yaml` | `provider: codex` + `allow_delegation: true`; proves dual-auth staging and delegation-skill install. |

> `multi-agent-claude-then-codex-markers.yaml` is **not** the codex bridge - it is
> `provider: claude-interactive` with `agent_id: codex` (a tmux pane). Do not use it
> to validate this section.

```bash
syn workflow run <codex-demo-workflow-id>
syn execution show <execution-id>
```

- [ ] Execution completes with phase exit 0

> **Exit-0 is load-bearing.** A codex run missing its terminal `turn.completed` event
> sets `error_reason` and the handler forces exit 1. Exit 0 therefore proves the
> stream terminated cleanly.

### Verify codex observability

```bash
syn sessions show <session-id>
syn events timeline <session-id>
syn costs session <session-id>
syn conversations show <session-id>
uv run python scripts/validate_codex_observability.py --execution <execution-id>
```

- [ ] Session records `agent_provider = codex`
- [ ] Timeline shows `Bash` ops (from `command_execution`) and `Edit` ops (from `file_change`)
- [ ] Token usage non-zero, with `cache_creation == 0` (codex reports no cache-creation)
- [ ] Exactly **one** session summary is recorded
- [ ] Cost is priced off `gpt-5.6` (alias of `codex`) - **not** a sonnet/haiku rate
- [ ] Transcript renders raw codex JSONL: `agent_message` as assistant text, `turn.completed` as `result`
- [ ] CLI banner noise is absent from the transcript (`Reading additional input from stdin`, `warning: --full-auto is deprecated`)
- [ ] `validate_codex_observability.py` exits 0

### Codex security assertions

```bash
# During/after the run, against the workspace container:
docker exec <workspace> ls -l /root/.codex/auth.json      # expect mode 0600
docker exec <workspace> ls /workspace/.setup/             # codex-auth.json must be GONE
docker exec <workspace> env | grep -E 'ANTHROPIC_API_KEY|CLAUDE_CODE_OAUTH_TOKEN'
```

- [ ] `~/.codex/auth.json` is mode 0600
- [ ] Staged `/workspace/.setup/codex-auth.json` was removed after setup (fail-closed check)
- [ ] A **pure codex** phase has NO `ANTHROPIC_API_KEY` / `CLAUDE_CODE_OAUTH_TOKEN` in its env (cross-provider isolation)
- [ ] No credential appears in container logs or process argv

### Delegation round-trip (optional, costs tokens)

```bash
syn workflow run <codex-delegates-to-claude-id>
```

- [ ] Both codex auth **and** claude env are staged when `allow_delegation: true`
- [ ] The `delegating-to-claude-p` skill is installed into the codex phase
- [ ] The transcript shows the primary agent actually invoking the other CLI
      (e.g. `tool_use Bash /usr/local/bin/claude`) and receiving a real answer back
- [ ] Delegated sub-agent sessions appear linked to the parent via `parent_session_id` (#792)

> **Do not infer credential staging from `docker exec <ws> env`.** Agent credentials are
> passed per-process via `workspace.stream(..., environment=agent_env)`, not baked into
> the container environment, so they are correctly invisible to `docker exec`. The valid
> test is whether the delegated CLI call succeeds.

> **Known gap (as of this revision):** a successful delegation produces exactly **one**
> session, with `parent_session_id: None`. The delegated call's tokens and cost are
> folded into the parent session. Assert the session **count** as well as the linkage -
> a single session for a delegating phase is a failure, not a pass.

### Dashboard - provider surface

- [ ] Session list and detail show an agent badge reading **"Codex"**
- [ ] A codex session shows **no** workspace-environment badge (shared image, by design)
- [ ] Workflow phase editor exposes a provider dropdown (Claude / Codex / Claude (interactive))
- [ ] Selecting **Codex** hides the model field (codex ignores `model`)
- [ ] Codex transcript lines render, including `log` lines for CLI diagnostics

---

## 6.2 Functional Validation - Skill Injection

> Added for harness-agnostic skill injection (#772 / #774). **Plan 1 of 3** - the CLI
> surface (`syn skill*`) is Plan 2 and does **not** exist yet.

### Known surface limits (do not treat these as bugs)

- The **only** write surface is `POST /skills/registrations`. There is no list, get,
  or delete endpoint, and no `syn skill` command.
- The marketplace does **not** serve skills, and `syn workflow install` does **not**
  preflight them. A marketplace workflow declaring `skills:` installs cleanly and then
  fails at execution with `SkillNotRegistered`.
- `claude_plugins` and `skills` coexist; nothing is deprecated until Plan 3.

### Precondition: the skills CLI must exist in the workspace image

```bash
docker run --rm "${SYN_WORKSPACE_DOCKER_IMAGE:-ghcr.io/agentparadise/agentic-workspace-claude-cli:latest}" skills --version
```

- [ ] `skills` CLI present (expected pin: 1.5.14)
- [ ] `skills add --help` accepts agent keys `claude-code`, `codex`, `gemini-cli`

> If this binary is missing, **every** skills-declaring phase fails at provisioning.

### Register a skill

The API does no git work - the client clones and POSTs the file tree (ADR-066).

```bash
git clone --depth 1 --branch <tag> https://github.com/anthropics/skills /tmp/sk
# Build payload: files[] = {rel_path (SKILL.md at root), content_base64}
curl -sS -X POST "$SYN_API_URL/skills/registrations" \
  -H 'content-type: application/json' -d @/tmp/payload.json
```

- [ ] 201 with `skill_name`, `resolved_sha`, `tree_storage_prefix` (`skills/sha256-<hash>`)
- [ ] Re-POSTing the identical body returns the **same** `resolved_sha` (idempotent)
- [ ] MinIO contains `skills/sha256-<hash>/manifest.json`

Negative cases:

- [ ] `rel_path: "../evil"` → 422 unsafe-path error code
- [ ] Malformed base64 → 400
- [ ] Tree with no `SKILL.md` → 422 manifest-missing
- [ ] > 10,000 files or > 50 MiB → 413

### Declare skills in a workflow

`skills:` is accepted at **both** workflow scope and phase scope. Phase-scope refs
merge with workflow-scope refs (deduped by `source_url` + `version` + `name`).

```yaml
skills:
  - "anthropics/skills/frontend-design@v1.2.0"   # org/repo/skill-name@version
  - "https://github.com/acme/tdd-skill@v2.0.0"   # <url>@<version>
  - source: github.com/acme/skills               # verbose form
    version: feature/branch-with-slash
    names: [alpha, beta]
```

- [ ] `@latest` is rejected
- [ ] Two-segment `org/repo@ver` (the plugin-era shape) is rejected with a corrective message
- [ ] Declaring an **unregistered** skill fails with `SkillNotRegistered` rather than running skill-less

> **No repo currently ships a skills-declaring workflow YAML.** Author one for this
> section; the closest reference is the fixture inside
> `packages/syn-domain/.../handlers/test_skills_end_to_end.py`.

### Prove the skill actually reached the agent

Staging alone is not proof - `.syn-skills/` is only the drop point; `skills add`
performs the per-harness install.

```bash
docker exec <workspace> ls -R /workspace/.syn-skills/<skill-name>
docker exec <workspace> skills list
docker logs syn137-api 2>&1 | grep "Installed .* skill"
```

- [ ] `/workspace/.syn-skills/<name>/SKILL.md` present in the container
- [ ] `skills list` (or `~/.claude/skills` for claude) shows the skill **installed**
- [ ] API logged `Installed N skill(s) for agent <key>`
- [ ] Conflicting versions of the same skill name abort the run (no silent last-wins)
- [ ] A phase declaring skills with a broken materializer **fails** - it must never run skill-less

---

## 6.3 Functional Validation - Claude Plugin Injection

> Added for workflow-scoped claude plugin injection (#726 / #764). Entire command
> group was absent from this runbook.

```bash
syn claude-plugin list                       # platform lock projection (API-backed)
syn claude-plugin installed                  # local install registry
syn claude-plugin show <name> <version>
syn claude-plugin install <ref>
syn claude-plugin install <ref> --global
syn claude-plugin global list
syn claude-plugin global add <name> <version>
syn claude-plugin global remove <name> <version>
```

- [ ] `list` returns the platform lock without errors
- [ ] `installed` reads the local registry
- [ ] `show` renders plugin metadata
- [ ] `install` registers a plugin and it appears in `list`
- [ ] `--global` promotes it; `global list` reflects it
- [ ] `global remove` demotes it

> **Note:** `syn claude-plugin installed` DOES exist, while `syn workflow installed`
> was renamed to `syn workflow packages`. Do not confuse them.

### Install preflight

`syn workflow install` resolves any `claude_plugins:` declared in the package YAML
**before** mutating the API.

- [ ] Installing a package with a valid `claude_plugins:` ref succeeds
- [ ] A package referencing an unresolvable plugin **aborts the install** cleanly
      (does not leave a half-created workflow)

---

## 7. Functional Validation - Trigger Lifecycle & Round-Trip

### Verify event poller is running before testing round-trips

> **Check this before spending time on round-trip tests.** If the poller failed
> to start, round-trip tests will fail silently (triggers registered, never fire).

```bash
docker logs syn137-api 2>&1 | grep -E "poller started|Polling error"
```

- [ ] "GitHub event poller started" line is present
- [ ] No "Polling error" lines
- [ ] If poller error is present: restart the API container (`docker restart syn137-api`) and recheck. If it persists, record as a blocker and skip round-trip sections.

### Determine available trigger presets

Based on Section 3 (webhook/polling mode):

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
# Note: action is part of the event name (e.g., issue_comment.created), not a separate flag
# Note: --workflow requires the FULL UUID (not a short prefix). Copy from `syn workflow list`.
syn triggers register \
  --event issue_comment.created \
  --repo <repo-id> \
  --workflow <workflow-uuid> \
  --max-attempts 5 \
  --cooldown 300
```

- [ ] Preset enabled successfully
- [ ] Custom trigger registered with safety limits
- [ ] `syn triggers list` shows both triggers
- [ ] `syn triggers show <trigger-id>` shows conditions and safety guards
- [ ] Registered trigger has a non-empty `installation_id` (v0.25.2 resolves `repo-*` IDs via the repo projection; empty ID means the App isn't installed on the repo from Step 5)

### Trigger pause/resume

```bash
syn triggers pause <trigger-id>
syn triggers show <trigger-id>
syn triggers resume <trigger-id>
```

- [ ] Trigger paused - shows paused status
- [ ] Trigger resumed - shows active status

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
- [ ] No duplicate triggers (dedup working - verify with a second poll cycle)

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
> `check_run.completed` which is webhook-only - not available via the Events API.

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

- [ ] `max_attempts` - trigger stops firing after limit reached
- [ ] `cooldown` - trigger respects cooldown period between fires

> **Partially testable.** `daily_limit` (20) and `debounce_seconds` (0) are hardcoded
> in the CLI and not exposed as flags, so only `max_attempts` and `cooldown` can be
> exercised end-to-end.

### Trigger cleanup

```bash
syn triggers delete <trigger-id> --force
syn triggers disable-all --repo owner/repo --force
```

- [ ] Individual trigger deleted
- [ ] All triggers for repo disabled

---

## 8. Functional Validation - Dashboard (Playwright)

> **Use Playwright for automated dashboard validation.** When run by Claude Code,
> use the `sdlc:browser-qa-agent` subagent type with Playwright MCP tools to
> validate the dashboard programmatically. This ensures repeatable, scriptable
> UI validation rather than manual browser checks.

Navigate to `http://localhost:8137` via Playwright.

**Key routes to validate:**

| Route | What to check |
|-------|---------------|
| `/` | Dashboard home loads, no JS errors in console |
| `/workflows` | Workflow list table renders |
| `/sessions` | Session list table renders |
| `/executions` | Execution list with status badges |
| `/triggers` | Trigger list with repo names (not UUIDs) |
| `/insights` | Overview charts and metrics |
| `/insights/cost` | Cost breakdown |
| `/insights/heatmap` | Activity heatmap |

### Navigation and rendering

- [ ] Dashboard loads without errors (check browser console for JS exceptions)
- [ ] All navigation links work (workflows, sessions, executions, triggers, insights)
- [ ] No broken images or missing assets (check network tab for 404s)

### Data views

- [ ] Session list renders with data
- [ ] Session detail view shows tool timeline and token breakdown
- [ ] Session detail shows `cost_by_model` breakdown (model name + cost, not empty)
- [ ] Execution detail view loads with phase progression
- [ ] Execution phases show `cost_by_model` breakdown per session
- [ ] Trigger detail shows human-readable repo name (`owner/repo`), not internal ID
- [ ] Trigger detail shows workflow name (e.g., "Code Review"), not UUID
- [ ] Trigger history visible and matches CLI output
- [ ] Cost/token metrics display correctly

### Real-time

- [ ] SSE connection active - `GET /api/v1/sse/activity` returns 200 and stays open (check network tab for the persistent SSE request, not a `ws://` WebSocket - the dashboard uses SSE)
- [ ] Dashboard shows green "Live" dot in top-right corner
- [ ] Live updates appear when new events are recorded

### Insights

> **As of v0.25.4 these three routes render the same "Coming Soon" placeholder** and are
> not distinct views. Validate that they load without a crash; do NOT assert on charts
> until the pages are implemented.

- [ ] `/insights` loads without a crash or error boundary
- [ ] `/insights/cost` loads without a crash or error boundary
- [ ] `/insights/heatmap` loads without a crash or error boundary
- [ ] If these now render real content, update this section and assert on the charts

---

## 9. Claude Code Plugin Validation

Run this section **after Section 8** (so sessions and executions from Section 6 exist for
`/syn-observe` and `/syn-executions show`).

> **Prerequisite:** `claude` CLI must be available. If the plugin is not yet installed:
> ```bash
> claude plugin install syntropic137
> ```
> The plugin connects to `http://localhost:8137` by default - the same selfhost stack
> used in Sections 0–8.

### Plugin update (always run first)

```bash
claude plugin marketplace update syntropic137
claude plugin update syntropic137@syntropic137
```

- [ ] Update completes without errors
- [ ] Plugin version matches expected release version

### Slash command smoke tests

| Command | What to verify |
|---------|---------------|
| `/syn-health` | Returns healthy status for `http://localhost:8137` |
| `/syn-status` | Lists all `syn137-*` containers with healthy status |
| `/syn-sessions list` | Returns session list (may be empty on fresh stack) |
| `/syn-costs summary` | Returns cost summary (may be zero on fresh stack) |
| `/syn-metrics` | Returns aggregated metrics without errors |
| `/syn-workflows list` | Returns workflows on the stack |
| `/syn-workflows search` | Returns marketplace results |
| `/syn-executions list` | Returns execution list (may be empty) |
| `/syn-marketplace list` | Shows registered marketplace sources |
| `/syn-triggers list` | Returns trigger list (may be empty) |
| `/syn-run <workflow-id>` | Starts an execution (after workflows exist from Section 6) |
| `/syn-observe <session-id> events` | Returns event timeline for a session from Section 6 |

- [ ] All commands above return results without errors
- [ ] No commands reference deprecated field names (`window_cost_usd`) or removed subcommands (`syn workflow installed` - renamed to `syn workflow packages`)

### Skill validation

Invoke these skills and verify they give correct guidance:

- [ ] **`execution-control` skill**: Walk through pause/resume guidance - references valid CLI flags
- [ ] **`observability` skill**: Query tool timeline for a session from Section 6 - session output uses server-rendered `*_display` fields (`total_cost_display`, `total_tokens_display`, `agent_model_display`, `duration_display`) per ADR-064, not client-formatted numbers
- [ ] **`marketplace` skill**: Workflow install/list guidance uses `syn workflow packages` (not `syn workflow installed`) with a note that `syn workflow list` shows the live stack

### Clean state note

`syn workflow packages` reads local CLI history (`~/.syntropic137/workflows/installed.json`), not
the stack. Clear it before a clean-slate plugin validation:

```bash
rm -f ~/.syntropic137/workflows/installed.json
```

---

## 9.5 Validate the Runbook Itself

> **Run this every time.** A validation runbook that has drifted from the code gives
> false confidence: it passes on commands that no longer matter and never exercises the
> features most likely to be broken (the new ones). This runbook was 4 months and 71
> commits stale when this section was added, and was missing every capability shipped
> in that window.

### Checkout currency check (do this FIRST)

Validating a stale checkout produces confident, wrong findings. A prior pass reported a
release-blocking cost bug that had already been fixed 5 commits ahead on `origin/main`.

```bash
git fetch origin
git status -sb | head -1          # must NOT say "behind"
git rev-list --count HEAD..origin/main   # must be 0
```

- [ ] Local `HEAD` is level with `origin/main` (or the divergence is deliberate and recorded)
- [ ] `git status --short` captured in the report, so results are attributable to a tree state

### Drift check

```bash
# When was the runbook last updated, and how much has landed since?
git log -1 --format='%h %ad %s' --date=short -- docs/testing/post-release-validation.md
git log --oneline $(git log -1 --format=%H -- docs/testing/post-release-validation.md)..HEAD | wc -l
git log --oneline $(git log -1 --format=%H -- docs/testing/post-release-validation.md)..HEAD \
  | grep -iE 'feat|BREAKING'
```

- [ ] Every `feat:` commit since the last runbook update maps to a section here, or is
      explicitly recorded as out of scope
- [ ] No section references a command that no longer exists

### Command coverage check

```bash
# Enumerate the real CLI surface and diff it against what this document exercises
grep -rn "registerCommand\|name:" apps/syn-cli-node/src/registry.ts | head -60
```

- [ ] Every command group in `registry.ts` appears in §4 or the feature matrix
- [ ] Commands referenced here still exist with the same flag signatures
- [ ] Every slash command in `lib/syntropic137-claude-plugin/commands/` is in §9
- [ ] Every skill in `lib/syntropic137-claude-plugin/skills/` is in §9

### Schema currency check

Generated schemas drift silently because `just docs-sync` does not cover them.

```bash
grep -A4 '"provider"' schemas/plugin/workflow.schema.json
grep -c '"skills"' schemas/plugin/workflow.schema.json
grep -c 'CODEX_AUTH_JSON' .env.example
```

- [ ] `provider` enum includes every value in `AgentProvider` (`claude`, `claude-interactive`, `codex`)
- [ ] `skills` is present in the published workflow schema
- [ ] Every Pydantic setting has a corresponding `.env.example` entry

### Deployment-parity check

Every credential the product needs must reach the API container in **all** overlays,
not just dev. This is the class of bug that makes a feature work for the maintainer
and fail for every user.

```bash
for f in docker/docker-compose.yaml docker/docker-compose.selfhost.yaml \
         docker/docker-compose.ondemand.yaml docker/docker-compose.syntropic137.yaml; do
  echo "== $f"; grep -cE 'ANTHROPIC_API_KEY|CLAUDE_CODE_OAUTH_TOKEN|CODEX_AUTH_JSON' "$f"
done
```

- [ ] Each agent credential appears in the selfhost overlay AND the published bundle,
      not only in `docker-compose.dev.yaml`
- [ ] `just gen-compose` regenerated after any overlay change

### After the run

- [ ] Findings folded back into this runbook as new checks (so the same bug cannot
      pass silently next time)
- [ ] Steps that failed *as written* corrected in place

---

## 10. Validation Report

### Where to save

Save the report to `docs/testing/output/` using the naming convention:

```
docs/testing/output/v<VERSION>-post-release-validation.md
```

Example: `docs/testing/output/v<VERSION>-post-release-validation.md`

This directory is **gitignored** (`docs/testing/output/.gitignore` excludes `*.md`), so
reports never pollute the commit history. They persist locally as reference artifacts
for closing gaps, planning hotfixes, and tracking launch readiness across versions.

### What to capture

The report is the primary context artifact for follow-up work. It should be
**self-contained** - a future Claude Code agent or developer should be able to read
this single file and understand exactly what works, what's broken, what's friction,
and what to do next.

The goal of Syntropic137 is frictionless onboarding for both users and agents. Every
finding should be evaluated through that lens: would a new user or a Claude Code agent
hit this? How bad is the experience?

### Report template

Copy and fill in after completing the runbook.

```markdown
# v<VERSION> Post-Release Validation

**Release version:** v_.__._
**Date:** YYYY-MM-DD
**Validated by:** <name or agent>
**Stack environment:** selfhost (`syntropic137_selfhost`)
**Webhook mode:** polling-only / webhook active
**Runbook:** [docs/testing/post-release-validation.md](../post-release-validation.md)

## What Passed

Summarize areas that work cleanly. Include counts (e.g., "24/24 CLI read-only
commands pass"). This builds confidence in what's solid.

## Findings (Ranked by Severity)

Every finding gets a severity, a clear description, root cause, fix suggestion,
and impact on the user/agent onboarding experience.

### P0 - Critical (blocks core functionality)

Release-blocking issues. The product cannot deliver its core value with these present.
Requires a hotfix release.

| # | Title | Root Cause | Fix | Impact |
|---|-------|------------|-----|--------|
|   |       |            |     |        |

### P1 - High (significant friction or breakage)

Not release-blocking but causes real pain. Should be fixed in the next release.

| # | Title | Root Cause | Fix | Impact |
|---|-------|------------|-----|--------|
|   |       |            |     |        |

### P2 - Medium (UX issues, incorrect behavior)

Works but the experience is wrong or confusing. Fix when convenient.

| # | Title | Root Cause | Fix | Impact |
|---|-------|------------|-----|--------|
|   |       |            |     |        |

### P3 - Low (cosmetic, minor inconsistencies)

Polish items. Address in a cleanup pass.

| # | Title | Root Cause | Fix | Impact |
|---|-------|------------|-----|--------|
|   |       |            |     |        |

### Info - Enhancements & Observations

Not bugs - ideas for improvement discovered during validation. Things that would
make the onboarding smoother, the DX better, or the product more self-explanatory.

| # | Title | Description | Value |
|---|-------|-------------|-------|
|   |       |             |       |

## Friction Log

Items that work but create friction for new users or agents getting started.
Evaluate each through the lens: "Would someone running `npx @syntropic137/setup`
for the first time hit this? How confused would they be?"

| Step | Friction | Severity | Suggestion |
|------|----------|----------|------------|
|      |          |          |            |

## Untested Areas

Items that could not be validated (e.g., blocked by a bug) and must be re-run
after fixes are applied. Include which runbook section(s) to re-run.

| Area | Blocked By | Runbook Section |
|------|------------|-----------------|
|      |            |                 |

## Feature Matrix

Full pass/fail/skip for every command and feature tested.

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
| syn workflow install/packages      |        |       |
| syn workflow create/status         |        |       |
| syn workflow run                   |        |       |
| syn workflow update (--dry-run)    |        |       |
| syn workflow export                |        |       |
| syn workflow delete/uninstall      |        |       |
| syn workflow info/init             |        |       |
| **Marketplace**                    |        |       |
| syn marketplace list/refresh       |        |       |
| syn marketplace add/remove         |        |       |
| **Agent Providers & Codex**        |        |       |
| codex credential reaches API       |        |       |
| workspace image has codex binary   |        |       |
| codex phase runs to exit 0         |        |       |
| session records provider=codex     |        |       |
| codex cost priced off gpt-5.6      |        | not haiku |
| codex transcript renders           |        |       |
| CLI banner noise filtered          |        |       |
| codex auth 0600 + staged file gone |        |       |
| no anthropic creds in codex phase  |        |       |
| codex->claude delegation           |        | optional |
| parent_session_id sub-session link |        |       |
| **Skills**                         |        |       |
| workspace image has skills CLI     |        |       |
| POST /skills/registrations         |        |       |
| registration idempotent (same sha) |        |       |
| unsafe path / bad base64 rejected  |        |       |
| workflow YAML `skills:` parsed     |        |       |
| skill installed in container       |        |       |
| unregistered skill fails loudly    |        |       |
| **Claude Plugins**                 |        |       |
| syn claude-plugin list/installed   |        |       |
| syn claude-plugin show/install     |        |       |
| syn claude-plugin global add/rm    |        |       |
| workflow install plugin preflight  |        |       |
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
| Real-time updates (SSE)            |        |       |
| Insights pages                     |        |       |

## Performance / Reliability Notes

-

## Recommended Actions

Ordered by priority. Link to GitHub issues when filed.

1.
2.
3.

## Launch Readiness Assessment

One paragraph: based on this validation, what is the state of the release relative
to open source launch? What must be fixed first, what can ship as-is?
```

---

## 11. Post-Fix Validation Loop

After the initial validation discovers issues and fixes are implemented locally,
verify those fixes against the selfhost stack before merging. This avoids shipping
a "fix" that passes unit tests but fails in the real deployment topology.

### Identify affected images

Map each fix to the Docker image it ships in:

| Fix area | Image to rebuild |
|----------|-----------------|
| API routes, domain logic | `syntropic137_development-api` |
| CLI (Node.js) | `syntropic137_development-cli` |
| Dashboard UI | `syntropic137_development-dashboard` |
| Gateway / nginx config | `syntropic137_development-gateway` |
| Collector | `syntropic137_development-collector` |

### Initialize submodules

The Docker build context requires submodule contents (event-sourcing-platform,
agentic-primitives). If working in a worktree or fresh clone:

```bash
git submodule update --init --recursive
```

### Rebuild affected images locally

Build only the images that changed. The build uses the base compose file plus the
selfhost overlay (which adds build args, entrypoints, etc.):

```bash
# From docker/ directory - build only the image(s) you need
cd docker

# API (includes domain packages + adapters)
docker compose -f docker-compose.yaml -f docker-compose.selfhost.yaml build api

# Gateway (nginx + security headers)
docker compose -f docker-compose.yaml -f docker-compose.selfhost.yaml build gateway

# Dashboard
docker compose -f docker-compose.yaml -f docker-compose.selfhost.yaml build dashboard
```

This produces local images named `syntropic137_development-<service>:latest`.

### Swap images into the selfhost stack

The selfhost stack at `~/.syntropic137/docker-compose.syntropic137.yaml` uses
pinned GHCR image digests. To use local builds, temporarily replace the image
references for affected services:

```bash
# 1. Find the current image lines
grep 'image:.*syn-api\|image:.*syn-gateway' ~/.syntropic137/docker-compose.syntropic137.yaml

# 2. Replace GHCR digest with local image name
#    Before: image: ghcr.io/syntropic137/syn-api@sha256:a4751f91...
#    After:  image: syntropic137_development-api:latest
#
#    Before: image: ghcr.io/syntropic137/syn-gateway@sha256:fbaaecad...
#    After:  image: syntropic137_development-gateway:latest
```

Then recreate only the affected containers:

```bash
docker compose -f ~/.syntropic137/docker-compose.syntropic137.yaml up -d --no-deps api
docker compose -f ~/.syntropic137/docker-compose.syntropic137.yaml up -d --no-deps gateway
```

Verify the containers restarted with the local images:

```bash
docker ps --filter "name=syn137-" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

- [ ] Affected container(s) show `syntropic137_development-<service>:latest` image
- [ ] Other containers unchanged (still on GHCR digests)
- [ ] `syn health` returns healthy after restart

### Re-run targeted validation

Do NOT re-run the entire runbook. Only re-run the sections that exercise the fixed
behavior:

| Finding | Re-validate with |
|---------|-----------------|
| API/domain fix | Section 4 (relevant commands) + Section 6 (workflow lifecycle) |
| CLI fix | Section 4 (relevant commands) |
| Gateway/CSP fix | Section 8 (dashboard - check console for CSP violations) |
| Cost calculation fix | Section 4 (`syn costs`, `syn execution show`) |
| Input validation fix | Section 6 (workflow run with missing inputs) |

```bash
# Quick smoke test after image swap
syn health
syn version
# Then run the specific commands that were broken
```

- [ ] Each finding's reproduction steps now pass
- [ ] No regressions in adjacent functionality
- [ ] Dashboard loads without new console errors

### Update the validation report

Append a "Post-Fix Re-Validation" section to the report in `docs/testing/output/`:

```markdown
## Post-Fix Re-Validation

**Date:** YYYY-MM-DD
**Images rebuilt:** api, gateway (list which)
**Commit:** <short SHA of fix commit>

| Finding | Status | Notes |
|---------|--------|-------|
| P1-1: ... | FIXED | Verified with ... |
| P1-2: ... | FIXED | ... |
```

### Restore GHCR images

After validation, restore the selfhost compose file to its original GHCR digests:

```bash
# Revert the image lines back to their original GHCR digests
# Before: image: syntropic137_development-api:latest
# After:  image: ghcr.io/syntropic137/syn-api@sha256:<original-digest>
```

> **Important:** Do NOT leave the selfhost compose pointing at local images.
> The next `npx @syntropic137/setup update` will overwrite the file anyway,
> but restoring avoids confusion if someone inspects the stack before then.

### Iterate if needed

If re-validation reveals new issues or regressions:

1. Fix locally
2. Rebuild the affected image
3. Swap into selfhost stack (edit image reference + `up -d --no-deps`)
4. Re-validate

Repeat until all findings are resolved.

### Cut a patch release

Once all findings pass re-validation:

1. Commit, push, and create a PR for all fixes
2. Merge to `main`
3. Bump version: `just bump-version <next-patch>`
4. PR `main` → `release` - triggers the full release pipeline
5. After release publishes, run `npx @syntropic137/setup update` on the selfhost
   stack to pull the new GHCR images with the fixes baked in
6. Run a final smoke test (Sections 1-4) against the updated selfhost stack
