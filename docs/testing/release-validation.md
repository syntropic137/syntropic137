# Release Validation Runbook

Step-by-step validation of a Syntropic137 release on a **selfhost stack**.

> Renamed from "post-release validation" on 2026-08-27. The process is
> unchanged; the name was wrong. Running it BEFORE cutting is the point, so a
> gap found here costs a fix rather than a hotfix. Nothing here requires a
> published release: [section 0-PRE](#0-pre-stand-up-a-pre-release-stack)
> stands up a stack from an arbitrary ref.
Run this before cutting a release, and again after, to catch regressions
before users hit them.

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

## 0.0 Gotchas - how a validation run lies to you

> Read this before running anything. Every entry below cost real time on
> 2026-08-21, several of them twice, and each one produces a **confident wrong
> answer** rather than an error.

The single failure mode behind almost all of them: **you validated something
other than what you think you validated.** A stale artifact, a different tier,
a cached tag, or your own test harness answers instead of the system under
test - and the answer looks legitimate.

### Stale artifacts - assert the identity of what you are testing

The same class bit three different ways in one day.

| What was stale | How it lied | The check |
|---|---|---|
| Running container 11 days old | Reported a pricing bug fixed 6 days earlier | `docker inspect <c> --format '{{.Created}}'` before trusting any result |
| Local `:latest` tag cached from an earlier pull | Showed exporter 0.1.1 when the registry had 0.5.0 | `docker buildx imagetools inspect <ref>` - asks the REGISTRY, not your daemon |
| Local git checkout behind origin | Validated code that had already been superseded | `git fetch && git status -sb` as step one |

**Environment variables are fixed at container-create time.** Editing a vault,
a `.env`, or a compose file changes nothing for a process already running. A
restart is not always enough either - `docker restart` reuses the existing
container and its environment. Recreate (`up -d --force-recreate`, or
`just dev-down && just dev`).

- [ ] Container build time is newer than the change under test
- [ ] Image digest resolved from the registry, not from a local tag
- [ ] Checkout is current with origin
- [ ] Config changes reached the process, verified with `docker exec <c> printenv`

### Absence looks exactly like success

Capture is fail-open, an empty store URL means "deliberately disabled", and a
missing test marker collects nothing. None of these produce an error.

**Zero is not a result until you can name what a non-zero would have required.**
On 2026-08-21 "0 captured sessions" had **five** independent causes, each
sufficient on its own and none of them logged:

1. compose never passed `SYN_SESSION_STORE_*` to the api service
2. the URL used a short hostname, unresolvable inside the workspace (musl)
3. the running container held a stale URL
4. a trailing space in the vault value made every upload target malformed
5. the phase ran on an image with no exporter

Before reporting a negative, establish a **baseline you expect to move**, and
confirm the mechanism could have worked at all.

- [ ] Baseline recorded before the run, from a source independent of the
      component under test
- [ ] Every precondition asserted, not assumed

### Your own harness is not evidence

Three false findings in one session came from the test, not the system:

- greps run from a subdirectory returned nothing, read as "this code does not
  exist" - it existed, six files of it. **Check `pwd` when a grep is
  surprisingly empty.**
- a hand-built request used the wrong Envoy hostname and returned 403; that was
  the harness being wrong, not the platform
- a status code was asserted on a route observed on a *different* instance of
  the same service (`/sessions` is 401 on one, 404 on another, because the real
  path is `/v1/sessions/batch`)

**Read the service's own contract** (`/openapi.json`, `--help`, the manifest)
rather than porting an expectation from somewhere else.

- [ ] A surprising negative was re-run from a known-good working directory
- [ ] Endpoints and routes come from the service's own spec

### Whitespace and quoting damage is invisible

A hand-pasted secret or URL carries whatever the editor added. A trailing space
does not show in a vault UI, in `echo`, or in most logs, and it fails deep
inside provisioning with the cause suppressed.

```bash
docker exec <c> sh -c 'printf "%s" "$SYN_SESSION_STORE_URL" | wc -c'
```

Compare against the expected length. Also: `op item get --fields --reveal`
CSV-quotes values containing quotes or commas, which reads exactly like a
corrupted secret - use `--format json`.

- [ ] Byte length of critical env values matches expectation

### A green test suite is not evidence that a guard is tested

Five separate times in two days, a test passed while covering nothing. Different
mechanism each time, same outcome: a guard nobody was actually checking.

| What passed | Why it proved nothing |
|---|---|
| `test_pricing_codex.py` | The wrong rate was written in as the expectation, so implementation and test shared one mistake |
| `TestLongContextIsTwiceShort` | Read 1 of 12 literals; the other 11 could be anything |
| `TestFormatCost` | Never marked `unit`, so `pytest -m unit` never ran it |
| `test_unpriced_cost_surfacing.py` | Injected a correct object past the broken function it claimed to test |
| A codex auth severity check | No fixture existed that only that check could reject |

**Mutation testing catches the first four and misses the fifth.** A mutant only
proves the paths it touches, so "I reverted the fix and tests failed" establishes
less than it feels like it does. The fifth case survived two rounds of mutation
work by an author who was actively looking for it.

The check that would have caught all five, for any guard you add:

> Name the fixture that fails if **only this guard** is removed, with every
> other guard intact.

If you cannot name one, the guard is untested no matter how green the suite is.
Two conditions ANDed together need a case that trips exactly one of them;
testing them jointly proves neither.

And when a mutant survives, the result is ambiguous rather than reassuring: it
means the code is dead **or** no test distinguishes it. Both readings deserve
checking, and the flattering one is the one to distrust.

- [ ] Every new guard has a fixture that isolates it
- [ ] A surviving mutant was investigated, not explained away

### A model's explanation of an error is not the error

Agent transcripts contain the agent's own account of what went wrong, written
confidently and usually first in the output. It is an interpretation, not a
reading, and it is frequently wrong in a specific way: the model latches onto
the most prominent line and builds a causal story around it.

On 2026-08-27 a delegated codex run failed. Claude reported:

> "The Codex sandbox encountered a permissions issue with bubblewrap."

The tool output underneath showed a bubblewrap WARNING that codex recovered
from, then an absolute-path complaint, and only then the real fault: a denied
user namespace. Two wrong fixes were attempted from the top of that stack
before anyone read to the bottom of it.

Read the `tool_result`, not the assistant text that follows it. When a log has
several plausible errors, the first one is the least likely to be the cause,
because the ones after it are what happened when the first was survived.

- [ ] Every failure diagnosis cites a tool result or a log line, not an agent's
      summary of one

### A 200 from an SPA is not a health check

The dev stack serves the dashboard on the same port as the API, with a
single-page-app catch-all. `GET :9137/health` returns **200 and an HTML
document**, because the SPA fallback answers every unmatched path. Any probe
built on it passes forever, including against a stack whose API is broken.

The API lives under `/api/v1/`. Probe a real endpoint and check the body, not
just the status:

```bash
curl -s -m 8 -o /dev/null -w '%{http_code}\n' http://localhost:9137/api/v1/workflows
```

- [ ] Health probes hit a real API route and assert on the payload

### Skill NAME and DESCRIPTION are in context; the BODY is not

Claude Code discloses skills progressively. The frontmatter `name` and
`description` are visible to the model; `SKILL.md`'s body loads only when the
skill is **invoked**. A validation that plants a marker word in the body and
then asks "list your skills" will see the skill NAMED and the marker ABSENT,
every time, on a perfectly working system.

That is a correct result being read as a failure. To prove the body loads, give
the skill a narrow `description` trigger, ask for exactly that task, and put the
assertion inside the body. Run a control phase with no skill so the evidence
cannot be explained by the model already knowing the answer.

- [ ] Skill tests distinguish DISCOVERY (name listed) from INVOCATION (body applied)

### Local codex and containerized codex share one refresh token

`CODEX_AUTH_JSON` in the vault and `~/.codex/auth.json` on the host carry the
same OAuth refresh token. Refreshing in one place invalidates the other: the
loser gets `401 refresh_token_reused` and the phase fails with zero tokens.

Running `codex exec` locally during a validation window can therefore break the
containerized codex phase you are about to validate, and the failure looks like
a platform bug rather than a credential collision.

- [ ] Codex credentials re-minted before a run that exercises codex phases
- [ ] Local `codex` not used concurrently with a containerized codex phase

### A green check belongs to a commit, not to a PR

`gh pr checks` and the PR page summarise the checks they last saw. Push a new
commit and that summary can still be showing the PREVIOUS commit's green while a
fresh run has only just started. Merging on it means merging code no check ever
ran against.

The tell is a PR that reads BLOCKED with **no failing checks**: that is what a
required check which has not reported yet looks like, not a glitch.

Before any merge, confirm the runs belong to the head SHA you are about to merge:

```bash
gh pr view <n> --json headRefOid -q .headRefOid
gh pr view <n> --json statusCheckRollup \
  -q '.statusCheckRollup[] | "\(.conclusion // .status)  \(.name)"'
```

"`gh pr checks` says green" and "green for the commit I am merging" are different
claims. Only the second one is a gate.

- [ ] Check runs verified against the head SHA being merged, not the PR summary

### Cold paths look like outages

A Tailscale route that has not been used recently returns connection failures
for the first few probes, then succeeds once the direct path is established.
The same is true of a container image being pulled on first use.

- [ ] A connectivity failure was retried before being reported

### Reachability is per-network, not global

The host and the workspace container resolve names and routes differently. A
store the host can reach may be unreachable from the agent network, and vice
versa. The exporter is a **musl static binary**, so it ignores
`nsswitch.conf`: short hostnames and `.local` names never resolve there even
when the host resolves them fine.

Always probe from **inside the image, on the agent network**:

```bash
docker run --rm --network <agent-net> --entrypoint sh <image> \
  -c "curl -s -m 15 -o /dev/null -w '%{http_code}\n' $URL/healthz"
```

- [ ] Reachability proven from the container that actually performs the work

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
> *"I'm at the workflow execution stage of the release validation. I need to
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
      provider: claude | codex
      model: <model-id>                     # forwarded to codex as --model
      allow_delegation: false
```

Canonical enum: `AgentProvider` in
`packages/syn-shared/src/syn_shared/agents.py`.

### Preconditions (codex)

Codex authenticates with a **file-injected `~/.codex/auth.json`** (ChatGPT
subscription), never an API key in argv or env.

```bash
# 1. Stage the credential. Production resolves it from 1Password via
#    scripts/op_env_export.py; `codex-auth-clip` copies the value so it can be
#    pasted into the vault item's CODEX_AUTH_JSON field (password/concealed).
#    Pasting into the root .env works for a quick local check but does NOT
#    exercise the production path - see the note below.
just codex-auth-clip                 # copies the raw value to the clipboard

# 2. The workspace image MUST contain the codex binary
# Resolve the image the stack ACTUALLY defaults to, rather than hardcoding one.
# A hardcoded fallback here silently validates a different image than the stack
# runs: the default moved from claude-cli to omni-agent, and a tag fallback is
# also rejected by image verification (registry refs must be digest-pinned).
WS_IMAGE="${SYN_WORKSPACE_DOCKER_IMAGE:-$(uv run python -c \
  'from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE; print(DEFAULT_WORKSPACE_IMAGE)')}"
echo "validating against: $WS_IMAGE"
docker run --rm "$WS_IMAGE" codex --version

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
**Which workflow you run decides which of the next two boxes applies.** The
shipped `workflows/examples/codex-demo.yaml` deliberately declares NO model, so
it CANNOT produce a priced result: `resolve_phase_model("codex", None)` returns
`None`, and this codebase never prices an unresolved model by substitution.
Running it and expecting a cost is asserting something the code cannot do.

- [ ] **Unmodelled run** (`codex-demo.yaml` as shipped): surfaces as UNPRICED.
      Never `$0.00`, never silently priced at another model's rate. Note that
      #890 can still render this as `$0.00` outside the cost-specific
      endpoints, so check a cost endpoint, not a session list.
- [ ] **Explicitly modelled run** (a workflow declaring `agent.model`, e.g.
      `gpt-5.6-sol`): cost is priced off the declared model, **not** a
      sonnet/haiku rate. An explicit non-Claude model IS preserved and passed
      through as `--model`; it is not dropped.

> **Settled 2026-08-26.** Codex DOES accept an explicit `gpt-5.6-sol` under
> ChatGPT auth: verified on `exec-9e55e62987a4`, which completed with
> `agent_model=gpt-5.6-sol` and a cost of $0.0299256, matching the corrected
> Standard short-context rates to seven decimals. The older warning in
> `codex-demo.yaml` named the ALIAS `gpt-5.6`, which is a different string and
> may still be rejected; name the concrete id. All three shipped codex examples
> now declare it. See issue #892.
>
> So the modelled branch above is the normal path. The unmodelled branch is kept
> to document what happens when a model is genuinely absent, not as a thing to
> aim for.

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

### Delegation matrix - both leaders, both directions (costs tokens)

**Run BOTH.** One direction passing does not imply the other. The two harnesses
stage credentials differently, delegate through different skills, and emit
different stream schemas, so claude-leads and codex-leads are genuinely separate
code paths. A single round-trip has repeatedly passed while its mirror was broken.

Each leader must delegate **twice**: once to a subagent of its own kind, and once
to the opposite harness. Same-kind delegation is the cheap common case;
cross-harness is where credential staging and stream parsing actually break.

| Workflow file | Leader | Delegates to | Verified |
|---|---|---|---|
| `workflows/examples/codex-delegates-to-claude.yaml` | codex | claude (`claude -p`) | 2026-08-27 |
| `workflows/examples/claude-delegates-to-codex.yaml` | claude | codex (`codex exec`) | 2026-08-27 |

These are single yaml files, not packages, so install them with `create --from`:

```bash
syn workflow create "Codex delegates to Claude" --from workflows/examples/codex-delegates-to-claude.yaml
syn workflow create "Claude delegates to Codex" --from workflows/examples/claude-delegates-to-codex.yaml
syn workflow run codex-delegates-to-claude
syn workflow run claude-delegates-to-codex
```

Both phases need `allow_delegation: true`; the leader's provider is set by
`agent.provider` on the phase. The platform installs a different baked skill per
direction, which is visible in the api logs and is a useful confirmation that
delegation was even attempted:

```
Installed baked delegation skill delegating-to-claude-p for agent codex
Installed baked delegation skill delegating-to-codex   for agent claude-code
```

#### Codex must bypass its own sandbox when it is the DELEGATE

A delegated `codex exec` inside a workspace container must use
`--dangerously-bypass-approvals-and-sandbox`, never `-s workspace-write`. Codex
sandboxes itself with bubblewrap, and bubblewrap cannot create an unprivileged
user namespace inside Docker, so every write in the delegated run fails.

The error is three layers deep and the top two both look like the answer:

```
warning: Codex could not find bubblewrap on PATH ... will use the bundled
         bubblewrap in the meantime            <- WARNING. codex continues.
bwrap: No permissions to create a new namespace, likely because the kernel
       does not allow non-privileged user namespaces.     <- the actual fault
Failed to write file /workspace/palindrome.py             <- the symptom
```

Installing bubblewrap does not help: a bundled copy is already in use and the
namespace is what is denied. The flag sounds reckless and is not: the workspace
container IS the sandbox.

- [ ] Delegated `codex exec` uses the bypass flag, and `< /dev/null`
- [ ] Delegated run's output appears in the parent transcript, not just a claim
      that it ran

#### Assert the delegation actually happened

A failed delegation currently reports `success=true` (issue #894). The primary
agent falls back to doing the work itself and records the fact in free text
inside its own `TASK_RESULT` comment, which nothing reads. So a green phase is
NOT evidence that delegation occurred.

- [ ] The delegate's own output is present in the transcript. For codex-leads,
      that means Claude's verdict text; for claude-leads, codex's `DONE`
- [ ] `TASK_RESULT.comments` does not contain "delegation failed"

#### Delegate cost is NOT captured yet

Known gap, issue #895. Record what you observe rather than expecting a pass:

- [ ] `cost_by_model` on the phase. TODAY this has ONE key, the primary agent
      only, even when the delegation demonstrably ran. Two keys means #895
      landed
- [ ] Session count for the execution. TODAY this is 1. Two linked sessions
      means #895 landed

Measured 2026-08-27: `exec-8634cc139420` (codex leads) recorded
`{gpt-5.6-sol: 0.226512}` and one session, while Claude's verdict text was in
the transcript. The delegate's tokens are unrecorded, so execution cost is
understated by the entire delegate leg.

Per run, assert:

- [ ] Both codex auth **and** claude env are staged when `allow_delegation: true`
- [ ] The leader's delegation skill is installed (`delegating-to-claude-p` in a
      codex phase, `delegating-to-codex` in a claude phase)
- [ ] The transcript shows the leader actually invoking each subagent
      (`tool_use Bash /usr/local/bin/claude`, `tool_use Bash .../codex`) and
      receiving a real answer back - not merely announcing an intent to
- [ ] **Session count >= 3** for the phase (leader + 2 delegates). One session is
      a failure, not a pass - see the known gap below
- [ ] Each delegated session carries `parent_session_id` pointing at the leader (#792)
- [ ] Every session has its own agent badge, and the badge matches the harness
      that actually ran (a codex delegate under a claude leader must read "Codex")

Across the pair, assert:

- [ ] Cost is attributed **per session with its own model rate** - the codex
      delegate priced off its declared model (`gpt-5.6-sol`), the claude
      delegate off its claude model.
      A single blended rate across a mixed execution is a defect
- [ ] Execution-level total equals the sum of its sessions
- [ ] `unpriced_observation_count` is 0 for both runs

> **Why the mirror matters.** In a claude-led phase the Envoy sidecar is active
> (Anthropic-only) and is skipped for codex phases. A codex delegate launched
> from inside a claude phase therefore needs egress the sidecar does not proxy.
> That asymmetry is invisible when only the codex-leads direction is tested.

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
- [ ] Selecting **Codex** hides the model field. NOTE: this is a UI limitation,
      not codex ignoring the value. An explicit non-Claude `agent.model` in the
      YAML is preserved and forwarded as `--model`; the dashboard simply does
      not expose model selection for codex yet.
- [ ] Codex transcript lines render, including `log` lines for CLI diagnostics

---

## 6.2 Functional Validation - Skill Injection

> Harness-agnostic skill injection (#772 / #774). **Plan 1 of 3** - the CLI surface
> (`syn skill*`) is Plan 2 and does **not** exist yet. Everything below was rewritten
> against the working implementation and re-derived from the skills CLI actually
> shipped in the pinned images; the previous version of this section predated the
> implementation and had never been run.

### The one thing to read before running anything

**`skills list --agent <key>` DOES NOT FILTER BY AGENT.** It prints every project
skill regardless of which harness each was installed for. Both keys return
byte-identical output:

```
$ skills list --agent claude-code          $ skills list --agent codex
Project Skills                             Project Skills
beta  ./.agents/skills/beta  Agents: not linked    beta  ./.agents/skills/beta  Agents: not linked
alpha ./.claude/skills/alpha Agents: Claude Code   alpha ./.claude/skills/alpha Agents: Claude Code
```

So a check shaped like "run `skills list --agent codex`, see the skill, tick the
box" **passes when the skill was installed for the wrong harness**. That is the
exact failure #772's agent-key table exists to prevent, and this command cannot
see it. Never gate on `skills list --agent`.

The real discriminator is the **install path**, which differs per harness:

| skills-CLI agent key | our `provider` / `agent_id` | install path under `/workspace` |
|---|---|---|
| `claude-code` | `claude` | `.claude/skills/<name>/SKILL.md` |
| `codex` | `codex` | `.agents/skills/<name>/SKILL.md` |
| `gemini-cli` | `gemini` (interactive-tmux pane only) | `.agents/skills/<name>/SKILL.md` |

Note that `codex` and `gemini-cli` share `.agents/skills`, so the path separates
claude from the rest but not codex from gemini. For codex, `skills list --json`
reporting `"agents": []` on a `.agents/skills` entry is expected, not a failure -
the CLI only reports a linked agent for the claude-specific directory.

### Known surface limits (do not treat these as bugs)

- Write surface is `POST /skills/registrations`. Reads are `GET /skills/registrations`
  and `GET /skills/storage`. There is still no delete endpoint and no `syn skill`
  command.
- The marketplace does **not** serve skills, but `syn workflow install` **does**
  preflight them: it registers every declared skill before creating any workflow, so
  a bad ref fails the **install**, not the run.
- `claude_plugins` and `skills` coexist; nothing is deprecated until Plan 3.
- `syn workflow install` is **not** idempotent for the workflow itself: re-installing
  a package whose workflow id already exists fails with "Concurrency conflict:
  expected version 0, got 1". This predates skill distribution - the skills preflight
  correctly reports "already registered" first. Use `syn workflow update` to
  re-install.
- Merge of workflow-scope and phase-scope `skills:` is keyed on the identity triple
  `(source_url, version, skill_name)`, **not** on skill name. Phase scope does not
  override a workflow-scope version by name; both survive the merge and the phase
  then aborts at provisioning with "conflicting versions". There is no by-name
  override mechanism in this plan.

### Precondition: the image actually running your phase has the skills CLI

```bash
just check-default-workspace-image
```

- [ ] claude, codex, and skills all report a version
- [ ] the image reported is the digest in `workspace_images.py`, not a tag

Then probe the specific image, resolved rather than hardcoded (the default moved
from claude-cli to omni-agent, and a tag fallback is rejected by image
verification anyway):

```bash
WS_IMAGE="${SYN_WORKSPACE_DOCKER_IMAGE:-$(uv run python -c \
  'from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_IMAGE; print(DEFAULT_WORKSPACE_IMAGE)')}"
echo "validating against: $WS_IMAGE"
docker run --rm --entrypoint sh "$WS_IMAGE" -c 'skills --version'
```

- [ ] `skills` CLI present, and the version it PRINTS is the expected pin (1.5.14)

> At the digests currently pinned in `workspace_images.py`, the skills CLI 1.5.14 is
> present in **all three** images (claude-cli, interactive-tmux, omni-agent), so a
> skills-declaring phase is not image-limited today. Nothing contractual guarantees
> that: no image build asserts the pin, and an operator override
> (`SYN_WORKSPACE_DOCKER_IMAGE`) can point at anything. Assert the version the
> command printed; never infer it from "the omni image has it".
>
> The **session exporter** (`apss-session-exporter`) genuinely IS omni-only - it is
> absent from claude-cli and interactive-tmux. Do not conflate the two binaries;
> §6.6 covers the exporter.

If the skills CLI is missing, **every** skills-declaring phase fails at provisioning
(loudly - `SkillInstallFailed`), which is the intended behavior.

### Register a skill

The API does no git work - the client clones and POSTs the file tree (ADR-066).

```bash
# NOTE: anthropics/skills publishes NO git tags. `git ls-remote --tags` returns
# nothing, so the '@v1.2.0' form this runbook used to show would 404. Pin a
# commit sha on main instead.
COMMIT=$(git ls-remote https://github.com/anthropics/skills main | cut -f1)
git clone --depth 1 https://github.com/anthropics/skills /tmp/sk
# Build payload: files[] = {rel_path (SKILL.md at root), content_base64}
curl -sS -X POST "$SYN_API_URL/skills/registrations" \
  -H 'content-type: application/json' -d @/tmp/payload.json
```

- [ ] 201 with `skill_name`, `resolved_sha`, `tree_storage_prefix` (`skills/sha256-<hash>`)
- [ ] Re-POSTing the identical body returns the **same** `resolved_sha` (idempotent)
- [ ] MinIO contains `skills/sha256-<hash>/manifest.json`

Negative cases:

- [ ] `rel_path: "../evil"` -> 422 unsafe-path error code
- [ ] Malformed base64 -> 400
- [ ] Tree with no `SKILL.md` -> 422 manifest-missing
- [ ] More than 10,000 files or more than 50 MiB -> 413

### Declare skills in a workflow

`skills:` is accepted at **both** workflow scope and phase scope.

```yaml
skills:
  # org/repo/skill-name@version. anthropics/skills publishes no git tags, so a
  # commit sha is the only pin that resolves against it.
  - "anthropics/skills/doc-coauthoring@3b3fad96af16a10759d930941b4520ba0c40edae"
  - "https://github.com/acme/tdd-skill@v2.0.0"   # <url>@<version>
  - source: github.com/acme/skills               # verbose form
    version: feature/branch-with-slash
    names: [alpha, beta]
```

- [ ] `@latest` is rejected in every form (shorthand, URL, verbose, `names:` expansion)
- [ ] Two-segment `org/repo@ver` (the plugin-era shape) is rejected with a corrective message
- [ ] Declaring an **unregistered** skill fails with `SkillNotRegistered` rather than
      running skill-less

### Both sources must be exercised

Skill distribution has two independent code paths; validating only one leaves the
other unproven.

| Source | How it is declared | How it is pinned |
|---|---|---|
| Vendored (in the plugin package) | `./skills/<name>` | sha256 of the file tree, computed by the CLI at install time |
| External (a git repo) | `org/repo/<name>@<ref>` or `<url>@<ref>` | the declared ref, resolved to a sha at registration |

A vendored skill has no version of its own, so the CLI pins it by tree hash and
uploads a definition in which every ref is explicitly pinned. Editing a vendored
skill therefore produces a NEW identity rather than silently resolving to the
previously stored tree.

Build the fixture once; the checks below all use it.

The fixture is committed, not built here: `workflows/examples/starter-plugin/`. It is the same artifact a
plugin author copies, so validating it validates what users actually get.
It declares a vendored skill (`./skills/repo-conventions`) and an external
one (`anthropics/skills/doc-coauthoring@<sha>`), diverging per phase, all
phases on `model: haiku` to keep a validation run cheap.

```bash
syn workflow install ./workflows/examples/starter-plugin
```

- [ ] A second `syn workflow install` prints `already registered` and performs **no**
      upload - this is the content-addressing claim. (The workflow-creation step
      itself will error; see the not-idempotent note above.)
- [ ] Editing `repo-conventions/SKILL.md` and re-installing registers a **different**
      `sha256-<hash>`
- [ ] Adding `- anthropics/skills/does-not-exist@3b3fad9...` makes the **install**
      fail and creates no workflow (`syn workflow list` unchanged)
- [ ] `GET /skills/storage` reports non-zero `object_count` and `total_bytes`

### Prove the skill reached the harness (deterministic checks)

Staging is not installation. `/workspace/.syn-skills/` is only the drop point;
`skills add <dir> --agent <key> -y` (run with cwd `/workspace`) performs the
per-harness install. Run these against the live workspace container.

```bash
# 1. Staged?
docker exec <workspace> ls -R /workspace/.syn-skills/<skill-name>

# 2. Installed WHERE? -- this is the check that actually discriminates harnesses.
docker exec -w /workspace <workspace> find /workspace/.claude/skills /workspace/.agents/skills \
  -maxdepth 2 -name SKILL.md

# 3. Machine-readable inventory (project scope; cwd matters).
docker exec -w /workspace <workspace> skills list --json

# 4. The lockfile the CLI writes.
docker exec <workspace> cat /workspace/skills-lock.json

# 5. Our side of the story.
docker logs syn137-api 2>&1 | grep "Installed .* skill"
```

- [ ] `/workspace/.syn-skills/<name>/SKILL.md` present (staged)
- [ ] For a **claude** phase: `/workspace/.claude/skills/<name>/SKILL.md` exists
- [ ] For a **codex** phase: `/workspace/.agents/skills/<name>/SKILL.md` exists
- [ ] The path matches the phase's provider. A claude phase whose skill landed in
      `.agents/skills` is the wrong-harness bug, and it is invisible to `skills list`
- [ ] `skills list --json` lists each skill with `"scope": "project"` and a `path`
      under `/workspace`. Run it with cwd `/workspace`; `skills list -g --json`
      returns `[]` because nothing is installed at global scope
- [ ] `/workspace/skills-lock.json` has a `skills.<name>.computedHash` entry per
      installed skill, and the hash changes when the source tree changes
- [ ] API logged `Installed N skill(s) for agent <key>` with the **expected** key
      (`claude-code` / `codex` / `gemini-cli`)
- [ ] Conflicting versions of the same skill name abort the run (no silent last-wins)
- [ ] A phase declaring skills with a broken materializer **fails** - never runs
      skill-less

### Prove the harness registered the skill (claude only, deterministic)

The claude stream-json `system` / `init` event carries a `skills[]` array read from
the harness's own registry **before any inference happens**. It is therefore
deterministic and model-independent - a real gate, not a vibe check.

```bash
docker exec -w /workspace <workspace> \
  claude -p --output-format stream-json --verbose 'exit' \
  | head -1 | jq '{type, subtype, skills}'
```

- [ ] The first event is `{"type":"system","subtype":"init"}` and its `skills[]`
      contains the installed skill name
- [ ] Skills whose `SKILL.md` frontmatter sets `userInvocable: false` are **filtered
      out** of `skills[]`. Absence there is expected for those and is not a failure;
      check the install path instead
- [ ] **Codex has no equivalent init event.** For codex phases, the install path and
      `skills list --json` are the whole deterministic story. Do not invent a codex
      version of this check

### Human-only step: is the skill actually reachable?

Ask the agent to list its skills, or give it a prompt the skill should trigger on.

**This is not a CI gate and must never become one.** The answer comes from
inference, so it is non-deterministic: a model can omit a skill it has, or claim
one it does not. Its value is catching "installed but not reachable" - correct file
in the correct directory that the harness nonetheless does not surface - which none
of the deterministic checks above can see.

- [ ] (human) A phase prompted to list its skills mentions the injected one, or acts
      on its content. Record the transcript link; if it does not, re-run before
      filing anything - one negative answer is not a bug report

### Failure modes that look like success

| Symptom | What actually happened | Check that catches it |
|---|---|---|
| Green run, agent ignores the skill | Wrong/overridden image with no or older `skills` CLI | `skills --version` inside the running container, asserting the printed pin |
| `.syn-skills/<name>/SKILL.md` present, agent unaware | Staged but `skills add` never ran or failed | Install path under `.claude/skills` or `.agents/skills` |
| `skills list` shows the skill, agent unaware | Installed for the WRONG harness | Install path. `skills list --agent` cannot see this |
| Install succeeds, run fails at provisioning | Skill declared but never registered | `SkillNotRegistered`; register via `POST /skills/registrations` first |
| Two versions of one skill name declared | Merge is additive across scopes; both survive | Provisioning aborts with "conflicting versions" - expected, not a regression |
| External ref 404s at install | `anthropics/skills` has no git tags | Pin a commit sha, not `@vX.Y.Z` |

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

## 6.35 Functional Validation - GitHub App CLI

> Added 2026-08-21 by the section 9.5 command-coverage check, which found this
> was the ONE command group in `registry.ts` with no section here. The runbook
> mentioned GitHub twenty times and exercised `syn github` zero times - all
> twenty were about the App's configuration, not its CLI surface. A group with
> no section is not a group that works; it is a group nobody looked at.

```bash
syn github repos
```

- [ ] `repos` lists repositories the App can reach, with owner, default branch,
      private flag and installation id
- [ ] The installation id matches the one configured for this tier
- [ ] A repo the App was granted access to appears; one it was not does not

The output is the App's view, not the org's. A repo missing here means the
installation lacks access to it, which is the thing to check FIRST when a
trigger never fires for a repo that plainly exists.

---

## 6.4 Functional Validation - SeshMagic Session Storage

> Added for the session-capture integration (syn137 #862/#863/#864, exporter
> v0.5.0, omni-agent manifest 1.3.0). Goal: every Syntropic137 agent session is
> retrievable from the central SeshMagic store, attributed to the deployment
> that produced it.

Claude and Codex transcripts are spooled inside the workspace container and
uploaded to a store speaking APS-V1-0004. The upload is performed by
`/usr/local/bin/apss-session-exporter`, which ships **in the omni-agent image
only**. A workspace running `claude-cli` captures nothing, and does so
silently.

**Capture is FAIL-OPEN by design.** A capture problem records `UNKNOWN`/`FAILED`
and asks for a backfill; it never turns a successful agent run into a failed
one. So a green workflow is NOT evidence that capture worked - only the recorded
verdict is.

### Preconditions

Assert the exporter version from inside the pinned image. Do not infer it from a
digest bump: the exporter's own release gate built a scratch image containing
only `.keep` for a period (agentic-session-exporter#22), so a green build proved
nothing about the published artifact.

```bash
OMNI=$(grep -A2 'OMNI_AGENT:' \
  packages/syn-shared/src/syn_shared/settings/workspace_images.py \
  | grep -o 'sha256:[a-f0-9]*' | head -1)
docker run --rm --entrypoint /usr/local/bin/apss-session-exporter \
  "ghcr.io/agentparadise/omni-agent-workspace@${OMNI}" --version
# expect: apss-session-exporter 0.5.0 (APS-V1-0004 SCS 1.0)

# Store reachable, and enforcing auth.
# Read the endpoint from the environment - never hardcode it. The value the
# platform actually uses is the only one worth probing, and it differs per
# tier. Resolve it the same way the API does.
STORE_URL=$(docker exec <api-container> printenv SYN_SESSION_STORE_URL)
test -n "$STORE_URL" || echo "capture is DISABLED on this stack"

# host.docker.internal is a container-side name; map it back for a host probe
PROBE_URL=${STORE_URL/host.docker.internal/127.0.0.1}
curl -s -o /dev/null -w 'healthz %{http_code}\n' "$PROBE_URL/healthz"

# Discover the write path rather than assuming it. Store versions differ:
# seshmagic 0.1.6 exposes POST /v1/sessions/batch, and a bare /sessions is a
# 404 there. Never encode a route observed on a different instance.
curl -s "$PROBE_URL/openapi.json" -o /tmp/store-api.json
python3 -c 'import json;d=json.load(open("/tmp/store-api.json"));[print(m.upper(),k) for k,o in d["paths"].items() for m in o]'
```

**Reachability must be checked from INSIDE the workspace image, not the host.**
The host and the container resolve names and routes differently, and the
container is the party that actually uploads:

```bash
docker run --rm --network <agent-net> --entrypoint sh \
  "ghcr.io/agentparadise/omni-agent-workspace@${OMNI}" \
  -c "curl -s -m 15 -o /dev/null -w 'healthz %{http_code}\n' $STORE_URL/healthz"
```

- [ ] Exporter reports `0.5.0` or later **from inside the pinned omni image**
- [ ] `/healthz` returns 200 **from the host**
- [ ] `/healthz` returns 200 **from inside the omni image, on the agent network**
- [ ] The write path exists in the store's own `/openapi.json`
      (seshmagic 0.1.6: `POST /v1/sessions/batch`)

> **Do not assert a status on a guessed path.** Routes differ between store
> versions: `/sessions` answers 401 on one instance and 404 on another, because
> the real write path there is `/v1/sessions/batch`. Read `/openapi.json`.
>
> The token is still mandatory. With a URL and no token, capture fails at
> finalize with the cause suppressed, and the run still goes green.

> **The phase must run on the omni image.** Confirm the workspace image in use
> before trusting a negative result - "nothing captured" and "wrong image" look
> identical from `/capture/status`.

### Configuration

Two variables enable capture. Both resolve from 1Password item
`syntropic137-config`, in the vault selected by `APP_ENVIRONMENT`
(`selfhost` -> `syntropic137`, `development` -> `syn137-dev`).

Field labels must match the variable names **exactly**. `op_env_export.py`
resolves an allowlist by label, so a differently-named field reads as
unconfigured even when the value is present in the vault.

| Field label | Value | Notes |
|---|---|---|
| `SYN_SESSION_STORE_URL` | tier-specific, e.g. `http://host.docker.internal:5361` | Empty disables capture entirely. Read it from the running container, never from this table |
| `SYN_SESSION_STORE_AUTH_TOKEN` | write token | Store as a concealed/password field |
| `SYN_SESSION_STORE_LABEL` | optional | `[A-Za-z0-9._-]{1,64}`; anything else ignored with a warning |

> **The URL is injected verbatim into the workspace container, so it must
> resolve THERE, not on the host.** `127.0.0.1:5361` is wrong - inside the
> container that address is the container itself. Use `host.docker.internal`,
> or attach `seshmagic-session-api` to the agent network and use its service
> name.
>
> A Caddy short hostname or a `.local` name will NOT resolve: the exporter is a
> musl static binary, and musl ignores `nsswitch.conf`. A real public DNS name
> is fine.

- [ ] Both fields present in the vault item for the tier under test
- [ ] Startup posture line names the deployment and **contains no part of the
      store URL** - that omission is the invariant, not a bug
- [ ] Startup warns when a URL is set with no token

### Validating a real capture

A clean startup proves nothing. The first workflow is the first real check.

```bash
syn workflow run <workflow-id>
syn capture status            # or: GET /api/v1/capture/status
```

- [ ] An entry exists for the phase that just ran
- [ ] `state` is **`captured`** - the ONLY value proving the store was reachable
      AND writable. `UNKNOWN` / `FAILED` mean capture did not happen
- [ ] `origin_deployment` matches the tier: `syntropic137__selfhost` from
      `syn137-api`, `syntropic137__development` from `syn-api`
- [ ] `agent_session_ids` is non-empty
- [ ] Each id fetched from the store returns a transcript whose content matches
      what the phase actually did

### Linkage - prove BOTH directions

Either direction alone can look correct while the join is broken.

**syn137 -> store.** `/capture/status` yields `execution_id`, `phase_id`,
`workspace_id`, `agent_session_ids[]`. The store keys on those agent-native ids.

**store -> syn137.** Every envelope carries host-supplied tags: `source`
(`syntropic137`), `execution_id`, `workspace_id`, `workflow_id`, `phase_id`,
`deployment`.

- [ ] Every id in `agent_session_ids` resolves to a session in the store
- [ ] That session's tags carry the same `execution_id` and `phase_id`
- [ ] Querying the store by `execution_id` tag returns exactly the sessions the
      execution produced - no more, no fewer

> **Prefer the tag direction when the two disagree.** Tags are host-supplied
> from the phase's environment block and are not forgeable by the agent.
> Session ids derive from transcript FILENAMES in an agent-writable spool.
>
> `workflow_id` exists on the store side only - `/capture/status` does not
> return it, so its absence there is not a defect.

### Multi-session capture (phase-to-many-sessions)

One phase can produce more than one agent session: a codex phase delegating to
`claude -p`, or a phase spawning subagents.

**As of 2026-08-21 this has only ever been exercised with hand-written
transcripts.** A run through the §6.1 delegation matrix is the first real
evidence, in either direction.

- [ ] Run a delegating phase and record how many ids `agent_session_ids` returns
- [ ] **State the count explicitly in the report, including when it is exactly
      1.** A single id from a genuinely delegating phase is a finding, not a pass
- [ ] Each id resolves to a distinct transcript in the store
- [ ] The delegated session's transcript is the OTHER harness's

### Known limits - do NOT report these as new findings

| Limit | Consequence for this run |
|---|---|
| No backfill yet (#861) | Spool is container-local. A SIGKILLed container loses its transcript and nothing retries. Capture is best-effort, not guaranteed |
| Absence, not substitution (#859, #843) | Ids come from agent-writable filenames, so a valid decoy would read as captured |
| `origin.host` is the CONTAINER ID | Not the machine. Use tags for identity, never `origin_host` |
| `origin.environment` is always `container` | It is a runtime CLASS. `origin.deployment` is the axis separating dev from selfhost |

### Concurrency

- [ ] `SYN_POLLING_MAX_CONCURRENT_DISPATCHES` is **UNSET**

The code default is now 1 (#866), because one execution's cancel or failure
tears down every other concurrently running execution's containers (#865, design
in #869). Pinning the value in compose means remembering to remove it when #865
is fixed and the default rises again. A deployment that raises it above 1 warns
at startup, naming #865.

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
| `/syn-setup` | Onboarding guidance; must not reference removed commands or stale ports |

- [ ] All commands above return results without errors
- [ ] No commands reference deprecated field names (`window_cost_usd`) or removed subcommands (`syn workflow installed` - renamed to `syn workflow packages`)

### Skill validation

Invoke these skills and verify they give correct guidance:

- [ ] **`execution-control` skill**: Walk through pause/resume guidance - references valid CLI flags
- [ ] **`observability` skill**: Query tool timeline for a session from Section 6 - session output uses server-rendered `*_display` fields (`total_cost_display`, `total_tokens_display`, `agent_model_display`, `duration_display`) per ADR-064, not client-formatted numbers
- [ ] **`marketplace` skill**: Workflow install/list guidance uses `syn workflow packages` (not `syn workflow installed`) with a note that `syn workflow list` shows the live stack

The plugin ships more skills than the three above. Every skill in
`lib/syntropic137-claude-plugin/skills/` must appear here - the 2026-08-21
section 9.5 sweep found eight that did not, which means nobody had checked
whether they still described commands that exist.

- [ ] **`setup`**: onboarding steps match the current `npx` flow and ports
- [ ] **`syn-workflow`**: create/run/inspect guidance matches current flags
- [ ] **`workflow-management`**: lifecycle guidance; no `syn workflow installed`
- [ ] **`syn-marketplace`**: matches the `marketplace` skill, no drift between the pair
- [ ] **`syn-triggers`**: uses `max_attempts` (not `max_fires`) and names the safety guards
- [ ] **`syn-control`**: pause/resume/cancel flags match `syn control --help`
- [ ] **`syn-insights`**: references endpoints that exist and cost fields that are current
- [ ] **`syn-repo`**: repo add/assign guidance matches `syn repo --help`
- [ ] **`organization`**: org/system/repo hierarchy guidance is current
- [ ] **`github-automation`**: references `syn github repos` and real trigger presets
- [ ] **`platform-ops`**: operational guidance names real containers and real ports
- [ ] **`troubleshooting-workflow-failures`**: the failure modes it names still exist,
      and the diagnostics it suggests still work

> **A skill that names a removed command is worse than a missing skill.** It
> reads as authoritative and sends the user somewhere that no longer exists.
> `syn workflow installed` -> `syn workflow packages` and `max_fires` ->
> `max_attempts` are both renames that already shipped, so both are live
> candidates for stale guidance.

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
git log -1 --format='%h %ad %s' --date=short -- docs/testing/release-validation.md
git log --oneline $(git log -1 --format=%H -- docs/testing/release-validation.md)..HEAD | wc -l
git log --oneline $(git log -1 --format=%H -- docs/testing/release-validation.md)..HEAD \
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

- [ ] `provider` enum includes every value in `AgentProvider` (`claude`, `codex`)
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
docs/testing/output/v<VERSION>-release-validation.md
```

Example: `docs/testing/output/v<VERSION>-release-validation.md`

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
# v<VERSION> Release Validation

**Release version:** v_.__._
**Date:** YYYY-MM-DD
**Validated by:** <name or agent>
**Stack environment:** selfhost (`syntropic137_selfhost`)
**Webhook mode:** polling-only / webhook active
**Runbook:** [docs/testing/release-validation.md](../release-validation.md)

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
| codex cost priced off declared model |      | not haiku; unnamed model = unpriced |
| codex transcript renders           |        |       |
| CLI banner noise filtered          |        |       |
| codex auth 0600 + staged file gone |        |       |
| no anthropic creds in codex phase  |        |       |
| codex->claude delegation           |        | optional |
| parent_session_id sub-session link |        |       |
| **Skills**                         |        |       |
| skills CLI version PRINTED = pin   |        | assert, don't infer |
| POST /skills/registrations         |        |       |
| registration idempotent (same sha) |        |       |
| unsafe path / bad base64 rejected  |        |       |
| workflow YAML `skills:` parsed     |        |       |
| `@latest` rejected in every form   |        |       |
| vendored skill pinned by tree sha  |        |       |
| external skill pinned by commit    |        | no tags upstream |
| install PATH matches phase harness |        | the real check |
| `skills list --json` + lock hash   |        |       |
| claude init event lists the skill  |        | claude only |
| (human) agent reaches the skill    |        | not a CI gate |
| unregistered skill fails install   |        |       |
| conflicting versions abort the run |        |       |
| **Claude Plugins**                 |        |       |
| syn claude-plugin list/installed   |        |       |
| syn claude-plugin show/install     |        |       |
| syn claude-plugin global add/rm    |        |       |
| workflow install plugin preflight  |        |       |
| **SeshMagic Session Storage**      |        |       |
| exporter 0.5.0 in omni image       |        | assert, don't infer |
| store /healthz 200, /sessions 401  |        |       |
| URL+token resolve from 1Password   |        |       |
| posture line leaks no store URL    |        |       |
| state=captured after a real run    |        | only real proof |
| origin_deployment matches tier     |        |       |
| agent_session_ids non-empty        |        |       |
| ids resolve to store transcripts   |        |       |
| store tags carry execution/phase   |        |       |
| multi-session count stated         |        | even if 1 |
| MAX_CONCURRENT_DISPATCHES unset    |        | #865/#866 |
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
