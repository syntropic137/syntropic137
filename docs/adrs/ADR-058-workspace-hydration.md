# ADR-058: Workspace Hydration — Pre-Cloned Repos and Synthetic CLAUDE.md

## Status

Accepted

## Date

2026-04-09

## Related ADRs

- [ADR-023: Workspace-First Execution Model](ADR-023-workspace-first-execution-model.md) — setup phase as infrastructure work
- [ADR-024: Setup Phase Secrets](ADR-024-setup-phase-secrets.md) — secret injection lifecycle, updated by this ADR
- [ADR-036: Workspace Structure Convention](ADR-036-workspace-structure-convention.md) — workspace directory layout, updated by this ADR
- [ADR-056: Workspace Tooling Architecture](ADR-056-workspace-tooling-architecture.md) — workspace image contract

## External References

- [AGENTS.md specification](https://agents.md/) — Linux Foundation AAIF standard
- [agentsmd/agents.md](https://github.com/agentsmd/agents.md) — specification source
- [Claude Code memory docs](https://code.claude.com/docs/en/memory.md) — @import depth limit, symlink support
- [Claude Code issue #6235](https://github.com/anthropics/claude-code/issues/6235) — AGENTS.md auto-load not yet supported
- [GitHub App installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app) — one token per installation
- [Git credential store path matching](https://git-scm.com/docs/git-credential-store) — per-repo URL entries

---

## Context

### The Problem: Agents Started Empty

Before this ADR, workspace containers started with the standard directory skeleton (`/workspace/artifacts/input/`, `/workspace/artifacts/output/`, `/workspace/repos/`) but no code. Repositories had to be cloned by the agent itself.

This had three compounding problems:

**1. CLAUDE.md was never loaded at startup.**

Claude Code discovers `CLAUDE.md` at launch from the working directory. When the container started, `/workspace/` had no `CLAUDE.md` and `repos/` was empty. The first thing an agent did was `git clone`, which placed the repo — and its `CLAUDE.md` — at `/workspace/repos/repo-name/`. But discovery already happened. The agent ran the entire session without project context loaded.

**2. Git clone was agent work, not agent _task_ work.**

From the observability dashboard, the first tool call for every execution was a `Bash: git clone ...` event. Infrastructure setup was consuming turn 1, inflating token counts, and burying the real work in the timeline.

**3. Multi-repo workflows required agent coordination.**

Workflows operating across two or more repositories (e.g. a platform repo + a submodule, or a plugin repo + a consumer) had no declared contract for which repos to clone or how to authenticate. Agents improvised, producing inconsistent layouts and auth errors on private repos.

### The Input Convention

Repos are passed as a comma-separated execution input:

```bash
syn run <workflow-id> --input repos="https://github.com/org/repo-a,https://github.com/org/repo-b"
```

The workflow template's existing single `_repository_url` field is supported as a backward-compatible fallback — treated as a single-element list if `repos` is not supplied.

---

## Decision

### 1. Pre-Clone Repos in the Setup Phase

The setup phase (introduced in ADR-024) is extended to pre-clone all declared repositories before the agent starts. Git clone is infrastructure work — it belongs in the setup phase alongside credential configuration.

The setup script appends per-repo clone commands with idempotency guards:

```bash
mkdir -p /workspace/repos

[ -d "/workspace/repos/repo-a" ] || git clone "https://github.com/org/repo-a" "/workspace/repos/repo-a"
[ -d "/workspace/repos/repo-b" ] || git clone "https://github.com/org/repo-b" "/workspace/repos/repo-b"
```

The idempotency guard (`[ -d "..." ] || ...`) ensures re-running the setup phase on a partially-hydrated workspace (e.g. after a crash and restart) does not re-clone repos that are already present.

Every repository a run recorded a commit for (`WorkflowExecutionStarted.source_commits`) is then checked out at that commit, between the clone and the submodule init - a resume's record being its parent's - and a commit that cannot be reached refuses the phase rather than falling back. A repository with no recorded commit stays at the default branch's head. See the addendum [Runs Check Out Their Recorded Commits (#1458)](#addendum-runs-check-out-their-recorded-commits-1458). The one exception is a phase that CONTINUES a branch: it is checked out at that branch's head (see [A Resumed Phase Continues Its Parent's Branch (#1513)](#addendum-a-resumed-phase-continues-its-parents-branch-1513)).

### 2. Inject Both `/workspace/AGENTS.md` and `/workspace/CLAUDE.md`

After the setup script completes, the Python layer injects both `AGENTS.md` and `CLAUDE.md` at the workspace root with **identical content**: direct `@`-imports of each repo's `AGENTS.md` followed by its `CLAUDE.md`.

```
@/workspace/repos/repo-a/AGENTS.md
@/workspace/repos/repo-a/CLAUDE.md
@/workspace/repos/repo-b/AGENTS.md
@/workspace/repos/repo-b/CLAUDE.md
```

```python
content = _generate_workspace_context(repos)
await workspace.inject_files([
    ("AGENTS.md", content.encode()),
    ("CLAUDE.md", content.encode()),
])
```

**Why two files:**

`AGENTS.md` is the [Linux Foundation AAIF standard](https://agents.md/) (donated December 2025 by OpenAI), natively loaded by 15+ agent platforms including OpenAI Codex, GitHub Copilot Coding Agent, Cursor, Devin, Gemini CLI, Windsurf, and Amp. See [agentsmd/agents.md](https://github.com/agentsmd/agents.md). Claude Code does **not** auto-load `AGENTS.md` ([issue #6235](https://github.com/anthropics/claude-code/issues/6235), 3,500+ upvotes, open as of 2026-04-09) — `CLAUDE.md` is therefore required.

**Why identical content (direct imports, not `CLAUDE.md → @AGENTS.md` indirection):**

Claude Code's `@import` depth limit is **5 absolute levels from the root file** ([Claude Code memory docs](https://code.claude.com/docs/en/memory.md)) with **no deduplication** — the same file imported twice loads twice into context. Each `@` import adds one absolute level regardless of which file contains it.

Using an intermediary (`CLAUDE.md` → `@AGENTS.md` → `@repo/AGENTS.md`) wastes one level and doubles context for repos that internally use `CLAUDE.md → @AGENTS.md`. Direct imports avoid both costs:

| Pattern | workspace file | repo file lands at | repo-internal imports | remaining depth |
|---------|---------------|-------------------|----------------------|-----------------|
| **Direct (chosen)** | L1 | **L2** | L3–L5 | **3 levels** |
| Indirection (`@AGENTS.md` shim) | L1 | L3 | L4–L5 | 2 levels |

Because Claude Code follows symlinks ([docs](https://code.claude.com/docs/en/memory.md#share-rules-across-projects-with-symlinks)), repos that make `AGENTS.md` a symlink to `CLAUDE.md` (or vice versa) avoid duplicate content entirely. The workspace injection is forward-compatible with that convention.

### 3. Multi-Repo GitHub App Token Resolution

Private repos require a GitHub App installation token for the `git clone` to succeed. Multiple repos may span multiple GitHub App installations (one installation per org or personal account).

**Resolution algorithm:**

1. For each repo URL, call `GET /repos/{owner}/{repo}/installation` to discover its installation ID.
2. If any repo returns **404** — it is not covered by any configured GitHub App installation — **fail fast** before any cloning starts, with a clear error message identifying which repo is uninstallable.
3. Group repos by `installation_id`. One GitHub App installation covers all repos in that org/account, so most single-org workflows resolve to one installation.
4. For each unique `installation_id`, call `POST /app/installations/{id}/access_tokens` to obtain one scoped installation token.
5. Write per-repo credential entries to `~/.git-credentials`:

```
https://x-access-token:TOKEN_A@github.com/org/repo-a
https://x-access-token:TOKEN_A@github.com/org/repo-b
https://x-access-token:TOKEN_B@github.com/personal/repo-c
```

Git's credential store supports URL path matching, so each clone uses the correct token automatically. No blanket `github.com` entry is written — per-repo entries are more precise and safer when multiple installations are present.

**Fail-fast invariant:** If installation lookup fails for _any_ repo in the list, the entire setup phase fails before any cloning begins. Partial hydration is not permitted.

### 4. Workspace Structure After Hydration

```
/workspace/
├── AGENTS.md                ← synthetic, injected at provisioning time
│                              identical to CLAUDE.md; for non-Claude platforms
├── CLAUDE.md                ← synthetic, injected at provisioning time
│                              identical to AGENTS.md; for Claude Code
├── artifacts/
│   ├── input/               ← previous phase outputs (read-only)
│   └── output/              ← current phase deliverables (agent writes here)
└── repos/
    ├── repo-a/
    │   ├── AGENTS.md        ← @-imported at L2 (direct, no intermediary)
    │   ├── CLAUDE.md        ← @-imported at L2
    │   └── ...
    └── repo-b/
        ├── AGENTS.md
        ├── CLAUDE.md
        └── ...
```

The `repos/` directory is now **pre-populated** before the agent process starts. Agents should navigate to `/workspace/repos/{name}` to begin work; they no longer need to clone.

---

## Alternatives Rejected

### Set cwd to `/workspace/repos/repo-a` at agent launch

**Rejected.** Works for single-repo workflows but breaks multi-repo: there is no single cwd that covers two repos. Also, `CLAUDE.md` discovery would still miss the synthetic root file since it walks up from cwd, not down from `/workspace/`.

### Let the agent clone on demand (status quo)

**Rejected.** The status quo is the problem being solved. Clone-on-demand means: no CLAUDE.md context at startup, git clone as the first observable tool call, and no structured auth model for multi-repo workflows.

### Inject context via the system prompt

**Rejected.** Pasting CLAUDE.md content into the system prompt does not enable recursive `@`-imports (which Claude Code resolves from the filesystem). It also inflates input tokens on every turn rather than loading once at startup via the file system.

### Single GitHub App token covering all repos

**Rejected.** A single blanket token for `github.com` works only when all repos belong to the same GitHub App installation. Multi-org or cross-account workflows require per-installation tokens. The per-repo resolution model generalizes to all cases and degrades gracefully to the single-token case when there is only one installation.

---

## Consequences

### Positive

- **Context from turn 1.** Agents start with full project context loaded. CLAUDE.md @-imports are resolved at launch, not discovered mid-session.
- **Clean observability.** The first tool call in the dashboard is now the agent's actual task, not infrastructure setup.
- **Multi-repo workflows are first-class.** The `repos` input supports N repos across multiple orgs. Auth is resolved per-installation, not per-repo.
- **Fail-fast on auth.** If a repo isn't covered by the GitHub App, the execution fails before wasting time on partial clones.
- **Idempotent setup.** The clone guard makes the setup phase safe to re-run after crashes (Processor To-Do List pattern — handlers must be idempotent).
- **Backward compatible.** The existing `_repository_url` single-field path still works — treated as a one-element `repos` list.

### Negative

- **Setup phase is longer.** Cloning repos adds latency before the agent starts. For large repos this could be 10–30 seconds. Acceptable for now; shallow clone (`--depth 1`) is a future optimization.
- **Synthetic CLAUDE.md is fragile if a repo has no CLAUDE.md.** If `/workspace/repos/repo-a/CLAUDE.md` does not exist, the `@`-import line is silently ignored by Claude Code. This is acceptable behavior but means agents won't receive context for repos that don't document themselves.
- **Installation lookup adds one API call per repo.** For N repos across M installations: N lookups + M token requests. For typical single-org workflows (N=1-3, M=1) this is negligible.

### Non-Consequences (Explicitly Out of Scope)

- **Skill injection (Phase 2).** Pre-staging skill directories at `/workspace/.claude/skills/` so Claude discovers installed skills at launch is architecturally supported by this hydration model but is a separate feature requiring its own ADR.
- **Shallow clones.** `--depth 1` for large repos is a future optimization, not part of this decision.

---

## Implementation Notes

### `SetupPhaseSecrets` changes

See the 2026-04-09 update in ADR-024 for the `SetupPhaseSecrets` API changes:
- New `repositories: list[str]` field
- `repo_tokens: dict[str, str]` replaces the single `github_app_token`
- `build_setup_script()` method replaces direct use of `DEFAULT_SETUP_SCRIPT`

### CLAUDE.md injection timing

The synthetic `CLAUDE.md` is injected **after** the setup script completes (repos are cloned) but **before** the agent process starts. This ordering is required — the `@`-import paths must resolve at inject time to verify the files exist.

### Repo name derivation

The repo name used in the clone path is derived from the last path component of the URL:

```python
repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
# "https://github.com/org/repo-a.git" → "repo-a"
# "https://github.com/org/repo-b"     → "repo-b"
```

### Known Limitation: Same-Name Repos Across Orgs

If two URLs produce the same repo name (e.g. `org-a/myapp` and `org-b/myapp`), only the first will be cloned — the second clone is silently skipped by the idempotency guard (`[ -d "/workspace/repos/myapp" ] || git clone ...`). The `@`-import lines for both repos are still injected, but only the first will resolve.

**Workaround (manual):** Rename one repo before passing the URL list, or fork one under a different name.

**Future fix:** Namespace clash detection in `build_setup_script()` -- suffix the second occurrence with the owner slug (e.g. `myapp` -> `myapp-org-b`). Tracked as a follow-up issue.

---

## Addendum: `requires_repos` Execution Gate (#666)

**Date:** 2026-04-11

### Problem

The preflight validation added alongside workspace hydration (Section 3) assumed all workflows need repositories. Workflows that don't require repos (research, analysis, artifact-only tasks) failed because:

1. `SeedWorkflowService` injected a placeholder URL (`https://github.com/placeholder/not-configured`) for workflows with `repository: null`
2. The preflight check tried to verify GitHub App access on this placeholder and returned a confusing error
3. Workflows with `{{repository}}` template variables failed with "Missing required inputs" when no repo was provided

### Decision

Add `requires_repos: bool` to workflow templates as an execution-time gate.

- **`requires_repos: true`** (default): Full preflight validation runs -- resolve repos, check GitHub App installation, fail if missing. This is the existing behavior.
- **`requires_repos: false`**: Skip repo validation entirely. The agent gets a bare workspace with no cloned repos. It can still run commands, do research, and save artifacts.

**Default is `true`** for backward compatibility -- all existing events in the event store were created assuming repos are required.

**YAML inference:** When `requires_repos` is not explicitly set in the YAML, the flag defaults to `true` (opt-out). An explicit `requires_repos: true/false` in the YAML always takes precedence. Research-style workflows that operate on no repos must opt out with `requires_repos: false`.

> **v0.25.2 update (2026-04-18):** The original inference rule was "infer from `repository` presence" -- workflows without a `repository:` block defaulted to `false`. With v0.25.2's ADR-063 typed-repos channel, the legacy `repository:` block is being phased out (workflows now declare `requires_repos: true` and accept repos via runtime `-R`), so inferring from its presence no longer matches the platform's primary use case. The new default is opt-out: omit `requires_repos`, get `true`. Migrated marketplace workflows (`code-review`, `sdlc-trunk` v0.2.0+) rely on this.

**Placeholder removal:** `SeedWorkflowService` no longer injects a `placeholder/not-configured` URL. Workflows without repos get `repository_url: ""`.

### Design Philosophy

Templates are higher-order prompts -- generic, reusable recipes that define the *shape* of work (phases, prompt structure), not the *target*. Repos and tasks are injected at execution time:

- **CLI:** `syn workflow run <id> --repo <url>`
- **Dashboard:** Repo picker (future, #667)
- **Triggers:** Webhook payload provides the repo
- **API:** `repos: [...]` in the execute request body

`requires_repos` gates the preflight validation pipeline, not the repo resolution itself. When `true`, the system validates GitHub App access before spinning up a container, ensuring fast failure. When `false`, the pipeline is skipped entirely.

---

## Addendum: `clone_repos` Per-Phase Checkout Gate (#1187)

**Date:** 2026-09-05

### Problem

Hydration was phase-blind. `WorkflowExecutionProcessor` builds one repo list
from the workflow and hands the same list to every phase;
`SetupPhaseSecrets.build_setup_script()` clones whatever it is handed. So every
phase of a workflow paid the same clone plus recursive submodule init,
regardless of what that phase does.

`sdlc-implement-v1`'s `open_pr` phase reads one artifact, checks a remote ref
and calls `gh pr create`. Its own prompt already tells it the branch is on
origin and that it must not push -- so the checkout it paid for was never used.
It nonetheless paid the full bootstrap under the shortest budget in the
workflow (600s against 1800-3600s elsewhere) and timed out in roughly 30% of
runs.

The only opt-out that existed was the `requires_repos` gate above, and it is
workflow-scoped: turning it off for `open_pr` would also have turned it off for
`implement` and `verify`, which genuinely need the checkout.

### Decision

Add `clone_repos: bool = True` at PHASE scope, alongside the existing
workflow-scoped `requires_repos`.

The two gates answer different questions, and the distinction is the point:

| | Scope | Question |
|---|---|---|
| `requires_repos` | workflow | Does this workflow have repos at all? |
| `clone_repos` | phase | Does THIS phase need them on disk? |

**Credentials and checkout are separated.** `clone_repos: false` still resolves
the GitHub App installation, mints the token, writes the per-repo
`~/.git-credentials` entries and configures `gh`'s `hosts.yml`. Only
`git clone` is skipped.

That separation is load-bearing, not incidental. The cheap way to skip a clone
was to pass no repositories -- but `repositories` is also what keys token
routing, so an empty list makes `_resolve_github_app_token` fall back to
`installations[0]`, which is the multi-org misrouting #1129 already fixed once.
A phase that talks to GitHub about a repo it does not need on disk previously
had no way to say so; this field is that way.

**The synthetic context follows the checkout.** Section 4's generated
`/workspace/AGENTS.md` and `/workspace/CLAUDE.md` are `@`-imports of paths under
`/workspace/repos/<name>/`. They are now derived from what was actually cloned,
so a no-clone phase does not receive imports pointing at files that do not
exist. This also removes the repo's own (large) `CLAUDE.md` from that phase's
auto-loaded context.

**Default is `true`**, for the same reason `requires_repos` defaults that way:
every phase already in the event store was written assuming a checkout.

### The Prompt Follows the Checkout Too

The shared preamble at
`packages/syn-domain/.../execute_workflow/workspace_prompt.py` was injected into
every phase and described `repos/` as "pre-cloned repositories (ready to use)",
with step one of a coding task being to navigate into
`/workspace/repos/<name>`. For a `clone_repos: false` phase both claims are
false, which meant the gate above could not be switched on: doing so sent the
agent into a directory that does not exist. `open_pr.md`'s "this workspace is a
fresh clone" said the same thing one layer up.

That constant is now `render_workspace_prompt(clone_repos=...)`, called from
`_build_workspace_prompt` with `phase.clone_repos`. A phase that clones renders
byte-for-byte what it rendered before - `test_open_pr_needs_no_working_tree`
holds a literal golden that fails on any drift - and a phase that does not is
told what it actually has: git credentials, a `gh` hosts.yml entry, and
`GH_REPO`, which is the whole of what this ADR provisions for it.

## Addendum: Runs Check Out Their Recorded Commits (#1458)

**Date:** 2026-10-03

### Problem

#1457 records, on `WorkflowExecutionStarted.source_commits`, the commit each
repository was at when an execution started, and a resume copies its parent's
record onto its own start event. Nothing read it. Every phase of every run
cloned the default branch's head, so a resume started after `main` moved on ran
its remaining phases on code its inherited phases never saw: a `plan` inherited
from the parent described one tree and `implement` edited another.

### Decision

**The execution decides, the setup script obeys.** Which commit a repository is
checked out at is a question about what the execution IS, so it is answered on
the aggregate, by `StartPins.checkout_commits()`:

| Run | `checkout_commits()` |
|---|---|
| Fresh | every `source_commits` entry with a sha - the commits it recorded at start |
| Resume | every `source_commits` entry with a sha - its parent's, copied onto its own start |
| Either, entry with `sha: None` | nothing for that repo - nothing resolved it when the run started, so there is no commit to hold to |

**A fresh run is pinned too.** The first cut pinned resumes only, reasoning that
a fresh run "started at now". It did not: `source_commits` is read when the run
starts and each phase clones when it is provisioned, so a push landing in
between - or between two of its phases - had the parent run a commit nothing
recorded, while its resume checked out the recorded one. Verification of #1525
reproduced it against a real git: both runs exited 0 on different HEADs. The
invariant is that **a run's recorded commit is the code it ran on**, and only
pinning the run that recorded it makes that true; recording each phase's actual
clone HEAD instead would give a multi-phase run several commits and a resume no
single one to hold to.

`PhaseWorkspace.provision` hands that answer to `WorkspaceProvisionHandler`,
which keys it by `owner/name` into `SetupPhaseSecrets.pinned_commits`.
`RepositoryRef` stays pure identity (ADR-063); a commit is not part of which
repository it is.

**The script.** For a pinned repository, directly after its clone line:

```bash
if ! git -C <dest> cat-file -e <sha>^{commit} 2>/dev/null; then
    printf '%s\n' 'ERROR: <owner/name> cannot be provisioned at its recorded commit <sha>: ...' >&2
    exit 65
fi
[ -n "$(git -C <dest> branch -r --contains <sha> 2>/dev/null)" ] \
    || git -C <dest> update-ref refs/remotes/pinned/<sha> <sha>
git -C <dest> -c advice.detachedHead=false checkout --quiet --detach <sha>
```

- **Before the submodule init.** Submodules then follow the gitlinks of the
  pinned commit, not the default branch's, so the whole tree is the parent's.
- **Detached.** No local branch is created or moved; whatever the phase
  commits, it names its own branch.
- **Reachable means "some branch or tag of origin reaches it".** The clone is
  full and fetches every branch and every tag, so a commit present after it is
  one origin still publishes, and no fetch-by-sha is needed. A commit that is
  absent was force-pushed away or its branch deleted, and is refused even if a
  fetch by id could still retrieve it: nothing on origin retains it, so it can
  be garbage-collected between two phases of the same resume.
- **A commit only a tag retains is accepted** (a release tag outliving a
  force-push). `--remotes`, which the unpushed-work guard and branch
  observation subtract, holds branches only, so a HEAD there would read as
  unpushed work. For that case alone the pin is recorded as
  `refs/remotes/pinned/<sha>`: under `refs/remotes` because origin does hold
  it, under its own remote name so it is never read as one of origin's
  branches. A commit a branch contains writes no ref. (Found by verification
  of #1525: the first cut required a containing branch and refused these.)
- **Only a full 40- or 64-hex commit id is ever interpolated.** Anything else
  raises `ValueError` while the script is rendered, so a value from the event
  store never reaches bash unvalidated.

**Unreachable means refused, never replaced.** A commit that was force-pushed
away or whose branch was deleted, and that no tag retains, exits the setup script with 65 (sysexits
`EX_DATAERR`; neither git nor bash uses it), and `WorkspaceProvisionHandler`
raises `PinnedCommitUnreachableError` - a `NonZeroExitError` - naming the phase,
the repository and the commit. Like every failure that is not the phase's own
report, it is classified PLATFORM. Falling back to the default branch would
quietly do the exact thing this addendum exists to prevent.

### Not Decided Here

- **#1513 - the resumed implement phase continuing the parent's pushed branch.**
  That is a per-phase choice ("this phase starts from the branch the parent
  pushed"), and it slots in at the same seam: `checkout_commits()` is the
  execution's answer and can become per-phase without re-threading anything
  between the aggregate and the script. Nothing here creates a local branch or
  forbids one.
- **Following the default branch within one run.** A run that wants a later
  phase to see commits merged to `main` while it ran cannot have that and a
  faithful record at once. None does today; it would be a per-phase choice at
  the same seam as #1513, recorded as its own commit.

## Addendum: A Resumed Phase Continues Its Parent's Branch (#1513)

**Date:** 2026-10-03

### Problem

A v3 implement phase opens a draft PR on its first push. A run that failed in
implement after that left a pushed branch and an open PR. Its resume checked
implement out detached at the pinned commit (#1458) and the agent, told
nothing, cut a second branch and opened a second PR for the same change.

### Decision

**The checkout rule.** A phase that READS code is checked out at the run's
pinned commit. A phase that CONTINUES a branch is checked out at that branch's
head. `StartPins.checkout_for(phase_id)` is the one place that says which: only
the resumed phase continues, and only branches its own earlier attempt left.
Every other phase, the resumed run's later ones included, reads the pinned
commit exactly as #1458 decided.

**Where the facts come from, all on the execution (Lane 1):**

| Fact | Recorded on | Source |
|---|---|---|
| Branches the failing phase left | the parent's `WorkflowFailed.observed_branches` (#1200) | git, asked while the workspace was alive, so it survives a phase that did not complete |
| The PR open from each of them | `BranchObservation.pull_request` on that same failure | `RemoteBranchPort`, asked as the parent fails (`with_open_pull_requests`) |
| Which of them the resume continues, with that PR | the child's `WorkflowExecutionStarted.continued_branches` | `RemoteBranchPort`, asked again as the child starts and compared with the above |
| Which it refused, and why | the child's `WorkflowExecutionStarted.abandoned_branches` | the same reading |

A branch counts as LEFT by the phase only when origin holds it and the phase
owned it: it did not exist on origin when the phase started, or the phase was
itself continuing it. A branch the phase merely sat on (`main` moving under a
fetch) is never continued. The observer reads the checked-out branch and also
every LOCAL branch no remote carried at phase start, so a phase that pushed B
and then checked out another branch before failing still records B.
`pull_request` is omitted when unset, like the start-event fields below. Both new fields are top-level, not inside
`resumed_from` (whose model forbids extra keys), and are omitted when unset, so
a release before #1513 replays the event unchanged.

**Stale is refused, visibly.** The child continues a branch only when the forge
confirms it is exactly where the parent left it AND the PR open from it is the
one the parent recorded. A PR opened from the same branch since (the parent's
#42 closed, #43 opened) is never adopted. Deleted, force-pushed or moved, the
parent's PR closed or replaced, or a forge nobody could ask: the branch is ABANDONED with that reason on the child's start event, a
warning is logged, the phase is told, and it starts fresh at the pinned commit.
"Could not ask" is never read as "gone", and never trusted either.

**The script.** For a continued repository the detached checkout is replaced
by:

```bash
if ! git -C <dest> merge-base --is-ancestor <head> refs/remotes/origin/<branch> 2>/dev/null; then
    printf '%s\n' 'ERROR: ...' >&2
    exit 65
fi
git -C <dest> checkout --quiet -B <branch> refs/remotes/origin/<branch>
git -C <dest> branch --quiet --set-upstream-to=origin/<branch> <branch>
```

A branch rewritten between the decision and the clone refuses the phase with
the #1458 exit code, never silently continuing someone else's history.

**The phase is told through the existing handoff.** `record_continuation`
adds a `resume-continuation` entry to the inherited phase-output cache, which
the prompt context renders under "Context from Previous Phases". It names the
branch and PR and says to push to it and not open a second PR. That is the
input the implement prompt's "If you are reworking an existing PR, use its
branch" path already keys on, so the prompt is unchanged.

### Not covered

- An interrupted or cancelled parent records no `observed_branches`, so its
  resume continues nothing and behaves as before.
- The PR is read from the forge as the parent fails, not observed at the
  moment `gh pr create` runs: the platform sees no PR being opened. A PR the
  forge could not be asked about then is recorded as none, so a PR found open
  at resume is refused rather than trusted.
