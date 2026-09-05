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

### The one rule the rest of this section is instances of

**An instrument that has never been observed failing is not known to be able to
fail.** Every gotcha below is a case of it, and they were all found the same way:
by making the thing being checked actually wrong and seeing whether anything
noticed.

Observing a green result is compatible with two states that look identical from
outside - the system is fine, or the instrument is blind. Nothing distinguishes
them except a run in which the thing being checked is genuinely broken.

So, per instrument:

| instrument | how you learn it can fail |
|---|---|
| a test | break the code it covers; confirm it goes red |
| a checker or script | corrupt its input; confirm it reports and exits non-zero |
| a CI signal | confirm it ran on **your** SHA, and that your test is selected |
| a health/status field | make the underlying thing unhealthy; confirm it changes |

Six instruments failed this way in a single session on 2026-08-27/28, each
reading success:

- four tests green on inputs that could not trigger the bug they guarded
- a CI pipeline green on a suite that never selected the failing test (#928)
- `git push` reporting "Everything up-to-date" and checks green, for a commit
  that was never pushed
- an acceptance checker green on a state it exited before examining

None had been observed failing, so none was known to work.

**Two habits that fall out of this and are worth doing every time:**

1. **A dry run on the healthy case tests nothing.** Watching a checker print the
   expected words is the same act as watching a suite pass - it is the
   observation that cannot distinguish the two states. Only the broken-input run
   is evidence.
2. **`cmd | tail` returns tail's status, not cmd's.** Exit codes read through a
   pipe are the pipe's. This bit two people in one session, in opposite
   directions: once concluding a passing run had failed, once the reverse.



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

### `main...HEAD` in a worktree attributes other people's commits to your branch

A worktree's local `main` ref does not move when `origin/main` does. So
`git diff main...HEAD` computes against a stale merge base, and everything that
landed on origin/main since then appears **inside your diff**.

This produced a confident, wrong review finding: a PR was reported as containing
"unrelated image-digest changes" that in fact belonged to a commit already
merged to origin/main. Acting on it would have reverted someone else's work.

It fails in both directions. It can also HIDE a change: if your branch touches
something that landed on origin/main after your stale ref, the three-dot diff
shows nothing for it.

```bash
git fetch origin                 # first, always
git diff origin/main...HEAD      # not main...HEAD
```

When a review claims a diff contains unrelated changes, check the base ref
before believing it. Provenance claims are as fallible as code claims, and
harder to spot because they sound like bookkeeping rather than analysis.

- [ ] Diffs and reviews computed against a freshly fetched `origin/main`

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

### A green check may have run on a commit you never pushed

`gh pr view --json statusCheckRollup` answers for whatever GitHub last saw at
the PR head. That is not necessarily what you built, and three independent
signals can all read success while the commit under test never left the laptop:

- a worktree in **detached HEAD** takes a merge commit off-branch
- `git push` then reports **"Everything up-to-date"** - true, and about a ref
  you are not on
- the PR still shows **all checks green**, for the older head

Measured 2026-08-28: local HEAD `1e09f36e`, PR head `6de24458`, and a check
monitor reporting "ALL GREEN, 28 checks, 0 failures" - for the wrong commit.

**Pin the question to a SHA whenever the answer matters:**

```bash
gh api repos/syntropic137/syntropic137/commits/<sha>/check-runs
git status -sb        # "## HEAD (no branch)" means detached
```

A **422 "No commit found for SHA"** means the commit does not exist remotely.
Nothing on the PR page tells you that.

- [ ] Before concluding from a green PR, confirm `headRefOid` equals the SHA you
      actually built, and query check-runs for that SHA
- [ ] After merging, confirm the merge commit is a real ancestor:
      `git merge-base --is-ancestor <merge-sha> origin/main`

This is the third shape of one problem, alongside the two already in this
runbook: a test that cannot fail, a test that is never selected (#928), and a
check that ran on a different commit. Each is a signal structurally incapable of
reporting the thing being asked of it, and each reads as success.

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

> **v0.28.0: this section will NOT show you the projection rebuild window.**
> Step 1 removes the data volumes, so Step 2 upgrades against an empty event
> store - there is nothing to replay, and the read-path window that a real
> v0.28.0 upgrade opens cannot occur here. A green run of this section is
> therefore not evidence that the window was handled. It is a rollout
> constraint, not a validation step, and it lives with the deploy:
> [v0.28.0 Rollout Constraints](../release-process.md#v0280-rollout-constraints).
> If you are instead validating an **in-place** upgrade (no `down -v`), follow
> that procedure before continuing here.

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
curl -s http://localhost:<port>/api/v1/health | jq .
```

> **Neither of these reports webhook or polling state.** Measured 2026-08-27:
> `syn health` prints only event-store and subscription lines, and
> `/api/v1/health` returns exactly `{status, mode, subscription, codex_auth}`.
> There is no webhook field to read. Use `/health` (no `/api/v1`) and you get the
> SPA's HTML 200, which looks like a passing check and is not one.
>
> Until a webhook-status field exists, determine the mode from the API logs
> instead - the poller announces itself at startup:
>
> ```bash
> docker logs <api-container> 2>&1 | grep -iE 'poller|polling'
> #   Poller cursor store initialized (ADR-060)
> #   Loaded N poller cursor(s) from database
> #   GitHub event poller started
> ```
>
> `Loaded 0 poller cursor(s)` plus an empty `SYN_GITHUB_APP_PRIVATE_KEY_FILE`
> means the poller is running with nothing to poll: no App credentials, so no
> installation, so no repos. **Every trigger section below is then unrunnable,
> not passing.** Do not record them as green.

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
syn control cancel <execution-id> --force     # --force is REQUIRED
syn control stop <execution-id> --force       # --force is REQUIRED
```

`cancel` and `stop` both refuse without `--force` (`Error: Use --force to
confirm ...`). That is a guard, not a bug, but a run that omits it records a
"cancel" that never happened.

**CANCEL STOPS SUBSEQUENT PHASES, NOT THE RUNNING ONE.** Measured 2026-08-27 on
`exec-d71bd8678ea4`: the phase that takes the signal continues to its own
natural end, because `interrupt()` logs

```
WARNING interrupt(): no container_id on isolation handle, skipping SIGINT
```

and never signals the container. What cancel does today is prevent the
remaining phases from starting. Assert that, not "the execution halts".

- [ ] `cancel --force` transitions the execution to `cancelled`, not `completed`
- [ ] Phases AFTER the cancelled one do not start
- [ ] The phase that took the signal may still finish; that is #918, still open
- [ ] Cancel WITHOUT `-r` behaves identically to cancel with one

> **The no-reason case is the one that matters.** Until #926, `interrupt_requested`
> was derived as `interrupt_reason is not None`, so a cancel carrying no message
> was silently ignored and the whole workflow ran on and billed in full. Every
> existing test passed a reason string and was green throughout. A cancel test
> that passes `-r` cannot tell a working build from a broken one - only the
> bare `--force` form can.
>
> #926 is merged but has NOT yet been confirmed on a live stack; it was verified
> at unit and processor level. Confirming it end to end is a job for this
> runbook, not a thing to assume.

**PAUSE IS NOT OBSERVABLE.** `syn control pause` returns 200 and prints
`Pause signal sent`, and then nothing changes: measured, the execution ran to
completion 45s later. No field in the execution payload reflects a pending
pause - there is no `paused`, no `pause_requested`, nothing. A following
`resume` fails with `Cannot resume execution in state running`, which is a
correct guard that the API surface gives an operator no way to understand.

- [ ] Record what pause actually does; do not mark it passing because the
      command returned 0. A 200 and a printed acknowledgement are not evidence
      the signal was honoured

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
# NOTE: there is no --file flag. `create` takes content inline, and --workflow
# is REQUIRED (omitting it fails with "Missing --workflow").
syn artifacts create --workflow <workflow-id> --content "probe-content-12345" \
  --type text --title "validation probe"
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

### Session store: metadata.model is not the pricing authority

`metadata.model` on a stored record is the **MODEL** for claude and the
**PROVIDER** for codex. Measured 2026-08-28 on live records:

```
codex   01a0472d  agent="Codex"       metadata.model = "openai"
claude  c5e2715f  agent="ClaudeCode"  metadata.model = "claude-sonnet-4-6"
```

Pricing from that field returns UNPRICED for every codex delegate, because
nothing has a rate for `"openai"`. The **transcript** is the authority.

**Why this is a validation step and not only a unit test.** The adapter's tests
pin this against a recorded fixture, so they document the asymmetry but cannot
notice the store changing - a test that reads a recorded value never sees the
world move underneath it. This check talks to the live store, which is the only
place the drift is observable:

```bash
for id in <codex-session-id> <claude-session-id>; do
  curl -s "$SYN_SESSION_STORE_URL/v1/sessions/$id" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); \
        print(d['agent'], '->', (d.get('metadata') or {}).get('model'))"
done
```

- [ ] A codex record still reports a provider-shaped value, not a model
- [ ] If it now reports a real model, that is a **finding**, not a fix: an
      advisory field silently becoming correct is how it gets promoted to an
      authority without anyone deciding to. Re-check what reads it before
      relying on it.

> **The direction is the trap.** metadata is CORRECT for claude and wrong for
> codex, so a "metadata usually works" shortcut passes a claude test and ships
> broken. The failure then looks like a pricing-table gap, and the tempting fix
> is to add a rate for `"openai"` rather than to read the transcript.

### Delegation matrix - both leaders, both directions (costs tokens)

**Run BOTH.** One direction passing does not imply the other. The two harnesses
stage credentials differently, delegate through different skills, and emit
different stream schemas, so claude-leads and codex-leads are genuinely separate
code paths. A single round-trip has repeatedly passed while its mirror was broken.

Cross-harness delegation is where credential staging and stream parsing actually
break, and it is what the two workflows below cover.

> **Same-kind delegation is NOT covered by any workflow file.** An earlier
> revision of this section asked each leader to delegate twice, once to its own
> kind. `workflows/examples/` contains only the two cross-harness files, so that
> instruction was unrunnable as written. If same-kind coverage is wanted, the
> workflows have to be authored first.

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

## 8.1 List Surfaces - Counts, Time Windows and Pagination

The three list surfaces named by the issues - **executions, sessions, artifacts** -
each shipped the same defect independently: a `total` that described the PAGE rather
than the collection, and history that no amount of paging could reach. #1159 (executions),
#1160 (sessions) and #1204 (artifacts) are all fixed. The repository owner
found all of it in a browser, because this runbook had no check that compared a
displayed count against anything.

Run this section against **every** list surface, not only the ones with a filed
issue. A check that skips the surface known to be broken stops being a check and
becomes a carve-out - and it was exactly "we already fixed that one" that let the
third instance ship.

> **This section covers a fourth surface the issues do not name: `/workflows`.**
> It carries the same contract as executions and sessions, and it shipped the same
> bug - its own code comment records `total` having been `len(summaries)`, so a
> client paginating until it had `total` items stopped after page 1. It was fixed
> without an issue number and has no regression coverage anywhere, which is the
> state executions and sessions were in before #1159. Two further surfaces are
> deliberately left out and recorded in `## Untested Areas`: `/triggers` (returns
> `total=len(rows)`, truthful only because the endpoint has no paging at all - a
> latent instance of the same shape) and `/costs/sessions` + `/costs/executions`
> (bare arrays capped at `limit<=200` with no `total` - the shape `/artifacts` had
> before #1204, and the last two surfaces still carrying it).

### How a list surface lies to you

Same shape as `## 0.0`: each row is a reading that is **confidently wrong** rather
than an error, and the right-hand column is the only thing that separates the two
states.

| What you see | What it can equally mean | What tells them apart |
|---|---|---|
| "50 executions" | 50 is the page size, and there are 330 | 8.1.1 - ask twice, at two page sizes |
| Same rows under "24h" and "7d" | The window is ignored - or is honoured, and page 1 is legitimately identical | 8.1.2 - read `total`, never the rows |
| History begins in June | Paging stops before the beginning of history | 8.1.3 - walk to the last page, then ask for older |
| A chip reading "completed 35" | 35 is this page's completed rows, against a true 235 | 8.1.4 - sum the chips against `total` |

The first one is the load-bearing one. **A surface where `total == len(rows)` at
every page size is self-consistently lying**: every field agrees with every other
field, the arithmetic closes, and no client can detect it from a single response.
Only a second request at a different page size can. That is why 8.1.1 comes first
and why it is two requests, not one.

### Preconditions - this section passes vacuously on a fresh stack

Every check in 8.1.1-8.1.4 is an assertion about a collection LARGER than one page.
On a stack just reset by `## 0` there are no rows, and all four return green having
examined nothing. (8.1.5 and 8.1.6 need no data and can run anywhere.) That is `## 0.0`'s "Absence looks exactly like success",
and a vacuous green here must be recorded as **NOT RUN**, never as PASS.

| Check | Minimum data for a conclusive result | If not met |
|---|---|---|
| 8.1.1 | `total` >= 2 | NOT RUN |
| 8.1.2 | rows in more than one of the 24h / 7d / older bands | NOT RUN (see the discriminator in 8.1.2) |
| 8.1.3 | `total` > `page_size`, i.e. more than one page | NOT RUN |
| 8.1.4 | `total` >= 1 | NOT RUN |

**8.1.1 needs two rows, not three hundred.** A `total` that echoes the page length
reports `total=1` when asked for one row and `total=2` when asked for ten. The
330-execution stack made the bug obvious; two rows make it provable.

Where to get the data: run this section against the **long-lived selfhost stack on
8137**, which carries real history. Every request in 8.1.1-8.1.5 is a `GET`; this
section writes nothing and is safe against accumulated data. A freshly reset
pre-release stack will only ever satisfy 8.1.1 (from the handful of executions
Sections 5-7 create) and cannot satisfy 8.1.2 at all.

### Setup - one set of helpers, four surfaces

```bash
export SYN_API_URL="http://localhost:8137/api/v1"
export SYN_API_USER="${SYN_API_USER:-admin}"
# SYN_API_PASSWORD must already be exported. Pass it by NAME, never by value -
# the literal then appears in no command line, no transcript and no shell history.

api() { curl -sS -u "$SYN_API_USER:$SYN_API_PASSWORD" "$SYN_API_URL/$1"; }

# The two numbers every list surface owes a client, however each one spells them.
rows_of()  { jq '(if type == "array" then . else (.executions // .sessions // .workflows // .artifacts // []) end) | length'; }
total_of() { jq -r 'if type == "array" then "ABSENT" else (.total | tostring) end'; }

# Percent-encode a value before it goes into a query string (see 8.1.5).
urlenc() { jq -rR '@uri'; }

# ISO 8601 UTC, $1 hours ago, offset included. GNU date first, BSD/macOS fallback.
iso_ago() {
  date -u -d "$1 hours ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -v-"$1"H +%Y-%m-%dT%H:%M:%SZ
}
```

- [ ] `api "executions?page_size=1" | total_of` prints a number, not `ABSENT`, not an error

The four surfaces, and where they differ:

| Surface | Endpoint | Rows | `total` | Page controls | Row timestamp |
|---|---|---|---|---|---|
| executions | `GET /executions` | `.executions` | yes | `page`, `page_size` (max 200) | `started_at` |
| sessions | `GET /sessions` | `.sessions` | yes | `page`, `page_size` (max 200; `limit` deprecated alias) | `started_at` |
| workflows | `GET /workflows` | `.workflows` | yes | `page`, `page_size` (**max 100** - 200 returns 422) | `created_at` |
| artifacts | `GET /artifacts` | `.artifacts` | yes | `page`, `page_size` (max 200; `limit` deprecated alias) | `created_at` |

Executions and sessions share one contract by construction
(`apps/syn-api/src/syn_api/list_query.py`), so a difference between those two is
always a finding. Workflows implements the same `total`/`page`/`page_size` shape
independently, so it can drift from them without any code changing on either side -
which is why it is checked here rather than assumed. Artifacts answered a bare array
with no `total` and no `page` until #1204; it now carries the same envelope as
sessions, down to the deprecated `limit` alias, and is checked like one.

Because unrecognised query parameters are ignored by all four endpoints, a single
URL carrying every spelling works against all of them - so one loop can ask all four
the same question, and the surface that answers differently is the finding.

> **Artifacts bounds its window on `created_at`, not `started_at`.** An unrecognised
> parameter is IGNORED rather than rejected, so `?started_after=...` against
> `/artifacts` returns the unfiltered collection and a `total` that looks like a
> window that was applied and did nothing. Send `created_after` / `created_before`
> to that surface; the table above is the authority on which noun each one takes.

### 8.1.1 `total` is invariant under page size

The one check that distinguishes a real count from a page length.

```bash
for surface in executions sessions workflows artifacts; do
  for ps in 1 10 50 100; do
    body="$(api "$surface?page=1&page_size=$ps&limit=$ps")"
    printf '%-11s page_size=%-4s rows=%-4s total=%s\n' \
      "$surface" "$ps" "$(rows_of <<<"$body")" "$(total_of <<<"$body")"
  done
done
```

Expected on a healthy stack with 330 executions, 97 sessions and 36 workflows:

```
executions  page_size=1    rows=1    total=330
executions  page_size=10   rows=10   total=330
executions  page_size=50   rows=50   total=330
executions  page_size=100  rows=100  total=330
sessions    page_size=1    rows=1    total=97
sessions    page_size=10   rows=10   total=97
sessions    page_size=50   rows=50   total=97
sessions    page_size=100  rows=97   total=97
workflows   page_size=1    rows=1    total=36
workflows   page_size=10   rows=10   total=36
workflows   page_size=50   rows=36   total=36
workflows   page_size=100  rows=36   total=36
artifacts   page_size=1    rows=1    total=214
artifacts   page_size=10   rows=10   total=214
artifacts   page_size=50   rows=50   total=214
artifacts   page_size=100  rows=100  total=214
```

**PASS** for a surface requires all three:

1. `total` is byte-identical across all four rungs.
2. `rows` equals `min(page_size, total)` on every rung.
3. At least two rungs produced different `rows` values - otherwise the collection
   is smaller than 2 and the check proved nothing (**NOT RUN**).

**FAIL** - `total` moves with `rows`. This is the #1159/#1160 shape:

```
executions  page_size=1    rows=1    total=1
executions  page_size=10   rows=10   total=10
```

**FAIL** - `total=ABSENT`. The surface returns a bare array and states no count at
all, so a client cannot page and cannot know what it is missing. No surface in this
section should read `ABSENT` any more; `/artifacts` was the last one and #1204 fixed
it, so an `ABSENT` here is a regression, not a known gap.

- [ ] precondition, per surface: at least two rungs returned DIFFERENT `rows`
      values (PASS condition 3). If every rung returned the same `rows`, the
      collection is smaller than two rows, and that surface's result is
      **NOT RUN** - no box below may be ticked PASS for it. A one-row stack
      reports `rows=1 total=1` on all four rungs, which satisfies condition 1
      while proving nothing
- [ ] executions: `total` identical across all four page sizes (condition 1)
- [ ] executions: `rows == min(page_size, total)` on every rung (condition 2) -
      a rung that returns fewer rows than the page size while `total` is larger
      is a FAIL, not a rounding detail
- [ ] sessions: conditions 1 AND 2, both
- [ ] workflows: conditions 1 AND 2, both
- [ ] all four of executions, sessions, workflows and artifacts satisfied
      conditions 1 and 2. A surface whose `total` tracks `rows` is reporting a page
      length, not a count, however self-consistent its response looks
- [ ] artifacts: conditions 1 AND 2, both - the same bar as sessions since #1204

### 8.1.2 Time windows actually narrow

```bash
# The bound's noun differs per surface - see the surface table. Sending the wrong
# one is not an error, it is an ignored parameter and a silently unfiltered total.
for surface in executions sessions artifacts; do
  case "$surface" in artifacts) bound=created_after;; *) bound=started_after;; esac
  for hours in 24 168; do
    printf '%-11s last %-5s total=%s\n' "$surface" "${hours}h" \
      "$(api "$surface?page_size=1&$bound=$(iso_ago "$hours" | urlenc)" | total_of)"
  done
  printf '%-11s all time  total=%s\n' "$surface" \
    "$(api "$surface?page_size=1" | total_of)"
done
```

Expected:

```
executions  last 24h   total=18
executions  last 168h  total=96
executions  all time   total=330
sessions    last 24h   total=6
sessions    last 168h  total=31
sessions    all time   total=97
artifacts   last 24h   total=11
artifacts   last 168h  total=58
artifacts   all time   total=214
```

`page_size=1` is deliberate: this check reads `total` and nothing else, and asking
for one row makes that unmistakable in the transcript.

> **The trap that has already produced a wrong PASS.** With more rows than one page
> in both windows, **page 1 is legitimately IDENTICAL between 24h and 7d** - the
> newest 50 rows are the newest 50 rows either way. An earlier validation attempt
> compared the visible rows, saw them unchanged, and concluded the window filter
> worked; the same observation is equally consistent with the filter doing nothing.
> **The acceptance criterion is that `total` changes. It is never that the visible
> rows change.** Do not add a row-comparison step here; it cannot decide anything.

**PASS** requires all of:

1. `total(24h) <= total(7d) <= total(all-time)` - monotonic, no exceptions. A
   DECREASE anywhere is an unconditional **FAIL** on its own - a wider window
   reporting fewer rows than a narrower one is broken regardless of the
   preconditions below.
2. When the precondition in the table above holds (rows exist in ALL THREE age
   bands: within 24h, from 24h through 7d, and older than 7d):
   `total(24h) < total(7d)` **AND** `total(7d) < total(all-time)` -
   BOTH strict. Either equality on its own is not sufficient for PASS; it must
   be resolved by the discriminator below, and an unresolved equality is
   **FAIL**, never PASS by default.
3. When the precondition does NOT hold, the result is **NOT RUN** - never
   PASS. A stack with history in only one age band cannot exercise the
   narrowing at all, and reporting PASS for it claims a check that did not run.

**If two totals are equal**, the window is either being ignored or a required age
band is genuinely empty. Establish the precondition by querying or inspecting rows
in EACH of the three bands; the oldest row alone cannot prove that the middle band
contains a row. There are THREE equality shapes, not one - cover all of them:

| Observation | Age-band evidence | Verdict |
|---|---|---|
| `total(24h) == total(7d) < total(all)` | a row exists in the 24h-through-7d band | **FAIL** - the 24h window is not being applied |
| `total(24h) == total(7d) < total(all)` | no row exists in the 24h-through-7d band | **NOT RUN** - the middle band cannot be exercised |
| `total(24h) < total(7d) == total(all)` | a row exists older than 7d | **FAIL** - the 7d window is not being applied |
| `total(24h) < total(7d) == total(all)` | no row exists older than 7d | **NOT RUN** - the oldest band cannot be exercised |
| `total(24h) == total(7d) == total(all)` | rows demonstrably exist in all three bands | **FAIL** - neither window is being applied |
| `total(24h) == total(7d) == total(all)` | any of the three bands has no row | **NOT RUN** - the full narrowing precondition is unmet |

**FAIL** - all three totals equal while history demonstrably spans more than 7
days. This is the #1159 shape where the window was applied in the browser to 50
already-fetched rows, so it could never change a server count. (This is the same
row as the last two lines of the table above, stated separately because it is
the shape #1159 actually shipped.)

- [ ] executions: precondition recorded (rows present in ALL THREE age
      bands) - if not met, the result below is **NOT RUN** and no other box in
      this item may be ticked PASS
- [ ] executions: `total(24h) <= total(7d) <= total(all-time)` with no
      decrease anywhere
- [ ] executions: `total(24h) < total(7d)` **AND** `total(7d) < total(all-time)`
      both strict - a single strict increase is not sufficient. Any equality is
      resolved via the discriminator table above; an equality left
      undiscriminated is **FAIL**, not PASS
- [ ] sessions: same three assertions
- [ ] artifacts: the same three assertions, bounded on `created_after` (#1204). A
      run that sent `started_after` here measured nothing: the parameter is ignored,
      so all three totals come back equal and the surface reads as broken when it is
      the query that was wrong
- [ ] workflows: **not applicable** - `/workflows` takes no time bound, so there is no
      window to narrow. This is a real gap in the surface (a 36-workflow list is
      browsable, a 3,000-workflow one is not) but it is not the defect under test
      here; it is recorded in `## Untested Areas`.

### 8.1.3 Paging reaches the end of history

Two failures hide here: arithmetic that does not close, and a `page` parameter that
is accepted and ignored. The second one still closes the arithmetic, so both checks
are required.

```bash
surface=executions; rows_key=.executions; id_key=.workflow_execution_id; ts_key=.started_at
ps=50; cap=200          # cap = this surface's max page_size; see the surface table

total=$(api "$surface?page_size=1" | total_of)
pages=$(( (total + ps - 1) / ps ))
last_rows=$(api "$surface?page=$pages&page_size=$ps"     | rows_of)
beyond=$(   api "$surface?page=$((pages+1))&page_size=$ps" | rows_of)

echo "total=$total pages=$pages last_page_rows=$last_rows beyond_last=$beyond"
echo "arithmetic: $(( (pages - 1) * ps + last_rows )) must equal $total"
```

Expected:

```
total=330 pages=7 last_page_rows=30 beyond_last=0
arithmetic: 330 must equal 330
```

**Pages must be disjoint.** If `page` is silently ignored, every page is page 1,
the arithmetic above still closes, and 280 rows are unreachable:

```bash
comm -12 \
  <(api "$surface?page=1&page_size=$ps" | jq -r "${rows_key}[]${id_key}" | sort) \
  <(api "$surface?page=2&page_size=$ps" | jq -r "${rows_key}[]${id_key}" | sort) \
  | wc -l
```

Expected: `0`. Any shared id means the pages overlap; `50` means `page` does nothing.

**Assertion 2 is a status code as well as a row count.** `rows_of` extracts
`.executions // .sessions // .workflows // []`, so a 404 or a 500 body has no rows
key, falls through to `[]`, and prints `0` - identical to a correctly empty page.
Read the code, not just the count:

```bash
curl -sS -o /dev/null -w 'beyond-last HTTP %{http_code}\n' \
  -u "$SYN_API_USER:$SYN_API_PASSWORD" \
  "$SYN_API_URL/$surface?page=$((pages+1))&page_size=$ps"
```

Expected: `beyond-last HTTP 200`.

**The last page must be the true beginning of history**, not the oldest row inside
some fixed recent window. Take the oldest reachable timestamp and ask the server
whether anything older exists - no date is hardcoded, so this check does not rot.

**Not `/workflows`** - it has no upper bound at all, and FastAPI IGNORES an
unrecognised query parameter rather than rejecting it, so running this against
workflows returns the unfiltered first page and reads as a catastrophic failure that
is really just a parameter that does not exist. See the workflows note below for what
to do instead. Artifacts DOES take one, spelled `created_before`; the same trap
applies to sending it `started_before`.

```bash
oldest=$(api "$surface?page=$pages&page_size=$ps" | jq -r "${rows_key}[-1]${ts_key}")
echo "oldest reachable: $oldest"

api "$surface?page_size=$cap&started_before=$(printf '%s' "$oldest" | urlenc)" \
  | jq -r "${rows_key}[]${ts_key}" | sort -u
```

Expected: exactly one distinct value, equal to `$oldest`.

```
oldest reachable: 2026-04-28T09:12:33.421000Z
2026-04-28T09:12:33.421000Z
```

`started_before` is INCLUSIVE, so the boundary row coming back is the check
working, not an off-by-one.

**PASS** requires all four:

1. `(pages - 1) * page_size + last_page_rows == total`.
2. Page `pages + 1` returns 0 rows (and a 200, not a 404 or a 500).
3. Pages 1 and 2 share zero ids.
4. The `started_before=$oldest` query returns no timestamp EARLIER than `$oldest`.

**FAIL** - assertion 4 returns older timestamps. Those rows are history that exists
in the store and that no sequence of page requests can reach. Report each distinct
timestamp; that set is the extent of the unreachable history.

Repeat the whole block for the other two paged surfaces by setting the variables at
the top. Nothing else changes:

```bash
surface=sessions;  rows_key=.sessions;  id_key=.id; ts_key=.started_at;  ps=50; cap=200
surface=workflows; rows_key=.workflows; id_key=.id; ts_key=.created_at;  ps=20; cap=100
surface=artifacts; rows_key=.artifacts; id_key=.id; ts_key=.created_at;  ps=50; cap=200
```

For artifacts, assertion 4's bound is `created_before` rather than `started_before`.

> **Workflows gets assertions 1-3 but not 4.** There is no `started_before` on the
> endpoint, so "is there anything older than the oldest reachable row" cannot be
> asked of it. What stands in for it: `/workflows` derives `total` from a store
> COUNT rather than from the rows it returned
> (`get_projection_mgr().workflow_list.count(...)`), so a `total` that under-reports
> history would have to be a wrong count rather than a page length - which 8.1.1
> already tests. Record the last page's oldest `created_at` in the report anyway,
> and note the missing bound; it is in `## Untested Areas`.

> **Known limitation on `/workflows`, do NOT report it as a new finding.**
> `order_by` sorts the current PAGE, not the collection, so with more than one page
> it gives no global ordering (the store orders on a text column, where
> `runs_count` would sort lexically - `"10" < "9"`). It is the same class as
> everything else in 8.1: a control that appears to act on the collection and acts
> on the page. Confirm it is still only that, and that the ROWS are still correctly
> paged despite it:
>
> ```bash
> api "workflows?page=1&page_size=5&order_by=-runs_count" | jq -r '.workflows[].runs_count'
> api "workflows?page=2&page_size=5&order_by=-runs_count" | jq -r '.workflows[].runs_count'
> ```
>
> Expected: each page descending WITHIN itself, page 2 not necessarily below page 1.
> **Escalate** only if the two pages share ids - that would be paging breaking, not
> the known sort limitation.

- [ ] precondition, per surface: `total > page_size`, i.e. `pages >= 2`. On a
      single-page collection the arithmetic closes trivially, page 2 is empty for
      free and pages 1 and 2 are disjoint for free - all four assertions pass
      having exercised no paging at all. If `pages < 2` that surface's result is
      **NOT RUN**, never PASS
- [ ] executions: arithmetic closes; page N+1 returns 0 rows **and HTTP 200** (a
      404 or a 500 also reads as 0 rows and is a FAIL, not an empty page); pages
      1 and 2 disjoint
- [ ] executions: nothing older than the oldest reachable row exists
- [ ] executions: `$oldest` recorded in the report as the earliest known record
- [ ] sessions: the precondition and the same four assertions
- [ ] workflows: the precondition and assertions 1-3 (`page_size` caps at 100, not
      200); assertion 4 is not available on this surface, so it is recorded as
      NOT RUN rather than ticked
- [ ] workflows: `order_by` behaves as the known limitation above, and no worse
- [ ] artifacts: the precondition and the same four assertions, with assertion 4
      bounded on `created_before` (#1204). Before it, `limit` was the only control
      and history past 200 rows could not be reached at all

### 8.1.4 The UI agrees with the API

Everything above tests the API. The defect reached the owner through the browser,
so the last check is that the browser shows what the API says. Use Playwright as in
`## 8`, with the browser reaching the dashboard via 8.1.6.

**Set the browser state by URL, not by clicking.** The list pages keep their
filters in the query string (`timeWindow` is one of `15m`, `1h`, `24h`, `7d`, `all`;
`status` is a comma-separated list), so navigating directly makes the browser's
query reproducible and provably the same one you sent to the API:

```
http://127.0.0.1:8138/executions?timeWindow=all
```

For each of `/executions` and `/sessions`, with **no status filter selected** and
`timeWindow=all`:

```bash
# The API's answer for the same query the UI just made.
# The dashboard's page size is 50 (LIST_PAGE_SIZE), so page 1 shows 1-50.
api "executions?page=1&page_size=50" | jq -c '{total, page_size, status_counts}'
```

Read off the page:

| UI element | Must equal |
|---|---|
| `Showing 1-50 of N executions` | `N` == API `total`; the `1-50` == `1-min(50, total)` |
| `Page 1 of M` | `M` == `ceil(total / 50)`. **Absent by design when `total <= 50`** - the controls only render when there is somewhere to go. Absent with `total > 50` is a FAIL |
| Status chips (`Pending`, `Running`, `Completed`, `Failed`, `Cancelled`) | see the chip arithmetic below |

**Chip arithmetic.** `status_counts` is tallied over every filter EXCEPT status, so
with no status selected the chips describe the same collection as `total` and MUST
sum to it. The dashboard renders a FIXED list of five statuses. There is exactly
ONE status the executions projection can emit that has no chip: `interrupted`. That
is the entire, named, enumerated exception - not a residual that absorbs whatever a
`status_counts` response happens to contain. Any status outside the five rendered
chips AND outside `interrupted` is not this exception and must not be folded into
the arithmetic; it is investigated on its own, below.

```bash
api "executions?page=1&page_size=50" | jq -r '
  ["pending","running","completed","failed","cancelled"] as $rendered
  | (.status_counts | to_entries) as $c
  | {
      total,
      chips_sum:   ([$c[] | select(.key | IN($rendered[]))                                   | .value] | add // 0),
      interrupted: ([$c[] | select(.key == "interrupted")                                     | .value] | add // 0),
      unexpected:  [$c[] | select(((.key | IN($rendered[])) or (.key == "interrupted")) | not) | .key]
    }'
```

Expected shape on executions:

```json
{"total":330,"chips_sum":310,"interrupted":20,"unexpected":[]}
```

Sessions has no `interrupted` status at all (`SessionStatus` is
`running`/`completed`/`failed`/`cancelled` - a subset of the five rendered chips,
`_shared/value_objects.py`), so on `/sessions` the named exception is EMPTY:
`interrupted` is always `0` and PASS requires `chips_sum == total` outright.

**The numbers that decide this check are the ones ON SCREEN.** The jq above reads
`status_counts` from the API, which is a cross-check, not the criterion: #1159 was a
browser showing "completed 35" while the collection held 235, and an API-only
assertion cannot see that. Read the five chips off the page and sum them
(`ResourceFilterBar` renders a fixed five, each as a button labelled
`<Status> <count>`):

```js
await page.goto('http://127.0.0.1:8138/executions?timeWindow=all')
const chips = {}
for (const label of ['Pending', 'Running', 'Completed', 'Failed', 'Cancelled']) {
  const text = await page.getByRole('button', { name: new RegExp(`^${label}\\b`) }).innerText()
  chips[label.toLowerCase()] = Number(text.replace(/\D+/g, ''))
}
const visible_sum = Object.values(chips).reduce((a, b) => a + b, 0)
console.log(JSON.stringify({ chips, visible_sum }))
```

Expected against the API response above:

```json
{"chips":{"pending":0,"running":2,"completed":235,"failed":68,"cancelled":5},"visible_sum":310}
```

**PASS** requires all three:

1. `visible_sum + interrupted == total`, where `visible_sum` is the sum of the five
   numbers READ OFF THE SCREEN and `interrupted` is the single named exception.
   This is the acceptance criterion.
2. `visible_sum == chips_sum` - every chip on screen shows the value
   `status_counts` reports for it. A chip that disagrees with the API is the #1159
   symptom exactly, and it is a FAIL even when the API's own arithmetic closes.
3. `unexpected` is empty.

On `/sessions` the named exception is empty, so condition 1 is
`visible_sum == total` outright.

**FAIL** - `visible_sum + interrupted != total`. This is the "completed 35 against a
true 235" shape: the visible chips (plus the one named, enumerated exception) do not
account for the total. The shortfall is real regardless of what else
`status_counts` contains - there is no other term available to balance the
equation.

**FAIL** - `visible_sum != chips_sum` while `chips_sum + interrupted == total`. The
API is right and the browser is wrong, which is the exact defect that reached the
owner. Passing on the strength of the API number alone is how it was missed.

**FAIL / escalate immediately** - `unexpected` is non-empty. A status exists outside
the five rendered chips and outside the single named exception. This is NOT
`interrupted` in another shape and must not be absorbed by widening the exception
list after the fact; investigate what emitted it and whether the dashboard needs a
sixth chip, and record it as its own finding.

**Finding, not a failure of this check** - `interrupted` is non-zero on executions.
Report it at P2 with the count; it is a smaller version of the same class (history
the UI cannot show), and it is not covered by #1159, #1160 or #1204. This finding
is independent of the PASS/FAIL verdict above: the check PASSES while this finding
is STILL recorded, because `interrupted` is a known, named, deliberate gap - not an
unexplained one.

**Selecting a status must move `total` to that chip's number.** This is the
"completed 35 against a true 235" symptom stated as an equation. Take the chip
counts from the unfiltered query above, then filter by one status - the filtered
`total` must equal exactly what that chip promised:

```bash
api "executions?page=1&page_size=50"                   | jq '.status_counts.completed'
api "executions?page=1&page_size=50&statuses=completed" | jq '.total'
```

Expected: the two numbers are identical (e.g. `235` and `235`). Navigate to
`http://127.0.0.1:8138/executions?timeWindow=all&status=completed` and confirm the
UI's `Showing 1-50 of 235 executions` carries the same number.

**PASS**: filtered `total` == that status's chip count, and the UI agrees.
**FAIL**: filtered `total` equals the row count of one page (50, or fewer) - the
chip was promising something the filter cannot deliver.

> Note that `status_counts` deliberately does NOT change when a status is selected -
> it is tallied over every filter EXCEPT status, so the chips keep saying what
> selecting each OTHER status would return. Chips that all drop to zero except the
> selected one is a regression, not the intended behaviour.

**Then page in the browser.** Requires `total > 50`. Click `Next` to page 2 and
confirm `Showing 51-<min(100, N)> of N` with **the same `N`**. A total that changes
while paging is the same defect wearing a different hat.

Then `/workflows`, which renders the same count line at a **page size of 20** and
has no status chips - so it gets the count assertions and not the chip arithmetic:

```bash
api "workflows?page=1&page_size=20" | jq -c '{total, page, page_size}'
```

- `Showing 1-20 of N workflows` where `N` == API `total`
- `Page 1 of M` where `M` == `ceil(total / 20)`

Finally, `/artifacts`, which renders the same count line at a page size of 50 and
has a type dropdown where the others have status chips - so it gets the count
assertions, and the dropdown's counts in place of the chip arithmetic:

```bash
api "artifacts?page=1&page_size=50" | jq -c '{total, page, page_size, type_counts}'
```

- `Showing 1-50 of N artifacts` where `N` == API `total`
- each type option's parenthesised count == `type_counts` for that type

**PASS**: the count line is present and matches the API. **FAIL**: no
`Showing X-Y of N` line at all - that was the pre-#1204 page, which fetched
`limit=100` with no statement that it was a page, so 101 artifacts rendered
indistinguishably from 500.

- [ ] precondition, per surface: API `total >= 1`. With `total == 0` every chip
      reads `0`, the arithmetic closes against nothing, and the result is
      **NOT RUN**, never PASS
- [ ] `/executions`: `Showing 1-50 of N` - both halves: `N` == API `total`, AND
      the displayed range == `1-min(50, total)`
- [ ] `/executions`: `Page 1 of M` matches `ceil(total / 50)` when `total > 50`.
      When `total <= 50` the control is absent BY DESIGN and this box is
      **NOT RUN**; absent while `total > 50` is FAIL
- [ ] `/executions`: `visible_sum + interrupted == total`, where `visible_sum` is
      summed from the five chips READ OFF THE SCREEN - an unresolved shortfall is
      FAIL, never PASS (PASS condition 1)
- [ ] `/executions`: `visible_sum == chips_sum` - each on-screen chip equals the
      `status_counts` value for its status. An API total that closes while a chip
      on screen disagrees is FAIL, not PASS (PASS condition 2)
- [ ] `/executions`: `unexpected` is empty; any entry is FAIL and is escalated as
      its own finding, never folded into the exception (PASS condition 3)
- [ ] `/executions`: any non-zero `interrupted` is reported as its own P2 finding
      (this does not change the PASS/FAIL verdict of the three items above)
- [ ] `/executions`: selecting a status moves `total` to exactly that chip's count
- [ ] `/executions`: `status_counts` unchanged by selecting a status
- [ ] `/executions`: paging to page 2 leaves `N` unchanged - requires `total > 50`;
      with `total <= 50` there is no page 2 and this box is **NOT RUN**, never PASS
- [ ] `/sessions`: every `/executions` assertion above, with the named exception
      empty - `interrupted` is always `0` on this surface (`SessionStatus` has no
      such status), so PASS here requires `visible_sum == total` outright, and ANY
      non-empty `unexpected` is FAIL
- [ ] `/workflows`: `Showing 1-20 of N` matches API `total` (range == `1-min(20,
      total)`), and `Page 1 of M` == `ceil(total / 20)` when `total > 20` -
      `ListPagination` hides the control at one page, so with `total <= 20` that
      half is **NOT RUN**; absent while `total > 20` is FAIL. No chips on this
      surface
- [ ] `/artifacts`: `Showing 1-50 of N` matches API `total` (range == `1-min(50,
      total)`), and `Page 1 of M` == `ceil(total / 50)` when `total > 50` -
      `ListPagination` hides the control at one page, so with `total <= 50` that half
      is **NOT RUN**. `type_counts` is tallied over every filter EXCEPT type, so
      selecting a type must not collapse the other options' counts to zero

### 8.1.5 A bound with no timezone is refused, not guessed

A window bound with no offset is ambiguous - local midnight and UTC midnight are
written identically - so the server refuses it rather than returning a confidently
wrong page (`_require_timezone`, #1183).

```bash
for bound in '2026-04-01T00:00:00' '2026-04-01T00:00:00Z' '2026-04-01'; do
  printf '%-22s -> %s\n' "$bound" \
    "$(curl -sS -o /dev/null -w '%{http_code}' -u "$SYN_API_USER:$SYN_API_PASSWORD" \
        "$SYN_API_URL/executions?started_after=$(printf '%s' "$bound" | urlenc)")"
done
```

Expected:

```
2026-04-01T00:00:00   -> 422
2026-04-01T00:00:00Z  -> 200
2026-04-01            -> 422
```

The 422 body must NAME the problem and the fix, not just reject:

```bash
api "executions?started_after=2026-04-01T00:00:00" | jq -r '.detail[0].msg'
```

Expected to contain `requires a timezone` and an example bound.

**PASS**: naive bound 422, aware bound 200, and the 422 message tells the caller
what to send. **FAIL**: a naive bound returns 200 - it was silently interpreted, and
every number downstream of it is wrong by the reader's UTC offset with nothing to
indicate it. A 500 is also a FAIL (that was the pre-#1183 behaviour).

> **`+00:00` must be percent-encoded, or the 422 is your bug and not the server's.**
> In a query string a literal `+` means a space, so
> `?started_after=2026-04-01T00:00:00+00:00` reaches the server as
> `2026-04-01T00:00:00 00:00`, fails to parse, and returns 422 - which reads exactly
> like the timezone check misfiring on a correctly-formed bound. It cost real
> debugging time. Send `%2B00%3A00`, or use `Z`, or pipe through `urlenc` as every
> command in this section does:
>
> ```bash
> curl -sS -o /dev/null -w '%{http_code}\n' -u "$SYN_API_USER:$SYN_API_PASSWORD" \
>   "$SYN_API_URL/executions?started_after=2026-04-01T00:00:00+00:00"     # 422 - the + became a space
> curl -sS -o /dev/null -w '%{http_code}\n' -u "$SYN_API_USER:$SYN_API_PASSWORD" \
>   "$SYN_API_URL/executions?started_after=2026-04-01T00:00:00%2B00%3A00" # 200
> ```

- [ ] Naive `started_after` returns 422 on `/executions`
- [ ] Naive `started_after` returns 422 on `/sessions` - the endpoints share the
      bound type, so a difference between them is a finding on its own
- [ ] Naive `created_after` returns 422 on `/artifacts` - same `WindowBound` type
      since #1204, on the surface that took no bound at all before it
- [ ] Aware (`Z`) bound returns 200 on both
- [ ] The 422 message names the fix
- [ ] The percent-encoded `%2B00%3A00` form returns 200

### 8.1.6 Reaching the dashboard in a browser without leaking the password

The dashboard and the API sit behind the same Basic Auth at the gateway, and
`http://admin:PASSWORD@localhost:8137` puts the password into browser history,
proxy logs, screenshots and this run's transcript. It is not recoverable once
written. Use a local reverse proxy that injects the header from the environment and
serves unauthenticated on loopback, then point the browser at the proxy:

```bash
cat > /tmp/syn-auth-proxy.mjs <<'PROXY'
// Injects the gateway's Basic Auth from $SYN_API_PASSWORD so the password never
// appears in a URL. Loopback only; kill it when the run ends.
import http from 'node:http'

const UPSTREAM = { host: '127.0.0.1', port: 8137 }
const AUTH =
  'Basic ' +
  Buffer.from(`${process.env.SYN_API_USER || 'admin'}:${process.env.SYN_API_PASSWORD}`).toString(
    'base64'
  )

http
  .createServer((req, res) => {
    const headers = { ...req.headers, host: `${UPSTREAM.host}:${UPSTREAM.port}`, authorization: AUTH }
    // Do NOT forward Accept-Encoding - see the gotcha below.
    delete headers['accept-encoding']
    const up = http.request({ ...UPSTREAM, path: req.url, method: req.method, headers }, (r) => {
      res.writeHead(r.statusCode, r.headers)
      r.pipe(res)
    })
    up.on('error', (e) => {
      res.writeHead(502)
      res.end(String(e))
    })
    req.pipe(up)
  })
  .listen(8138, '127.0.0.1', () => console.log('http://127.0.0.1:8138'))
PROXY

SYN_API_PASSWORD="$SYN_API_PASSWORD" node /tmp/syn-auth-proxy.mjs &
curl -sS -o /dev/null -w 'proxy %{http_code}\n' http://127.0.0.1:8138/api/v1/workflows
```

Expected: `proxy 200`. Then navigate Playwright to `http://127.0.0.1:8138`.

- [ ] Proxy returns 200 for a real API route (not just `/`, per `## 0.0` "A 200 from an SPA is not a health check")
- [ ] The password appears in no URL, no screenshot and no log line from this run
- [ ] Proxy killed at the end of the run

> **The proxy gotcha that looks exactly like a broken dashboard build.** The gateway
> has `gzip on`. If the proxy forwards the browser's `Accept-Encoding: gzip` but
> strips or fails to preserve `Content-Encoding: gzip` on the way back, the browser
> receives gzipped bytes labelled as plain text. The SPA's JS bundle then fails to
> parse and the console reads:
>
> ```
> Uncaught SyntaxError: Invalid or unexpected token
> ```
>
> which is indistinguishable from a corrupt build, and sends you to rebuild an image
> that was never broken. Two correct fixes, and the failure is in mixing them:
> either **do not forward `Accept-Encoding`** (as above - upstream then sends plain
> text and there is nothing to mislabel), or forward it and pass `Content-Encoding`
> through untouched. Never strip one and keep the other.
>
> Confirm which you got before blaming the dashboard:
>
> ```bash
> curl -sS -D- -o /dev/null http://127.0.0.1:8138/ | grep -i 'content-encoding'
> ```
>
> Expected with the proxy above: no `content-encoding` header at all.

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
| `/triggers` count and pagination | Not checked. `total` is `len(rows)`, truthful only because the endpoint is unpaged - a latent instance of the 8.1 shape that becomes a lie the moment a `limit` is added | 8.1 |
| `/costs/sessions`, `/costs/executions` count and pagination | Not checked. Bare arrays capped at `limit<=200` with no `total` - the shape `/artifacts` carried until #1204, and the last two surfaces still carrying it | 8.1 |
| `/workflows` time-window filtering | No `started_after` / `started_before` parameter exists on the endpoint, so 8.1.2 has nothing to assert | 8.1.2 |
| `/workflows` global `order_by` | Known limitation: sorts the current page, not the collection (text-column ordering in the store). Not a regression - do not file | 8.1.3 |
| Statuses with no dashboard chip (e.g. `interrupted`) | The UI renders a fixed five-status chip list; a status outside it can be neither displayed nor filtered. Report the count if seen, but the UI behaviour is unvalidated | 8.1.4 |
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
