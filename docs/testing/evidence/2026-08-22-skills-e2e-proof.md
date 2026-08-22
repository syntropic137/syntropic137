# Per-phase skills reach the agent inside the container: end-to-end proof

Date: 2026-08-22
Stack: dev stack, API `http://localhost:9137`
Execution: `exec-3db1801d5a3c`, workflow `skillproof-research-v1`, 2 phases, `model: haiku`
Cost: $0.10294625 (investigate) + $0.0197156 (summarize) = **$0.1226619**

## What this closes

PR #876 built a plugin that declares per-phase skills and proved it *installs and
registers*. PR #874 proved the skills-CLI install semantics against the real image,
but synthetically (`docker run` plus `skills add` directly). Neither ran a workflow.

The unproven chain was: **install -> resolve -> materialise -> `skills add` ->
agent-can-use-it, per phase, through a real execution.** This document captures that
chain running for real, with output taken from inside live phase containers.

## Setup

PR #876's commit `53d7cafe` was **cherry-picked** onto a worktree branched from
`origin/main` (not a branch checkout), so the starter plugin exists here as
`workflows/examples/starter-plugin/`.

The plugin's workflow ids `starter-research-v1` and `starter-pr-review-v1` were
already burned on this stack. Per issue #822, `syn workflow delete` does not free an
id, so the ids were changed rather than fought:

```
id: starter-research-v1   ->  id: skillproof-research-v1
id: starter-pr-review-v1  ->  id: skillproof-pr-review-v1
```

The CLI was built from this worktree (`pnpm build` in `apps/syn-cli-node`), because
#876 also carries the `shared://` phase-prompt resolver fix without which the plugin
is uninstallable.

## The declaration under test

`workflows/examples/starter-plugin/workflows/research/workflow.yaml`:

- **workflow scope**: `./skills/repo-conventions` (VENDORED, pinned by tree sha256)
- **phase `investigate`**: adds `anthropics/skills/doc-coauthoring@3b3fad96...` (EXTERNAL)
- **phase `summarize`**: declares nothing

Expected, if per-phase scoping works:

| phase | expected skills |
|---|---|
| `investigate` | `repo-conventions` + `doc-coauthoring` |
| `summarize` | `repo-conventions` only |

`doc-coauthoring` being **absent** from `summarize` is the claim that matters.

## Link 1: install -> registry (PROVEN)

```
$ SYN_API_URL=http://localhost:9137 node dist/syn.js workflow install /tmp/skillproof-plugin
Package Preview
  starter-plugin v1.0.0
  Format: multi
  Workflows: 2
  Total phases: 4

Resolving 2 skill(s)...
  skill repo-conventions@sha256-7df181458fe2692519efad5a46b88953d1d0228aa8a81c6d43a14f7167cac4e2 already registered
  skill doc-coauthoring@3b3fad96af16a10759d930941b4520ba0c40edae already registered
  [1/2] Creating Starter PR Review... done (id: skillproof-pr-review-v1)
  [2/2] Creating Starter Research... done (id: skillproof-research-v1)
```

`skill_lock` projection (`syn-db`, database `syn`):

```
./skills/repo-conventions|sha256-7df1814...|repo-conventions
  {"version": "sha256-7df181458fe2692519efad5a46b88953d1d0228aa8a81c6d43a14f7167cac4e2",
   "skill_name": "repo-conventions", "source_url": "./skills/repo-conventions",
   "resolved_sha": "7df181458fe2692519efad5a46b88953d1d0228aa8a81c6d43a14f7167cac4e2",
   "tree_storage_prefix": "skills/sha256-7df181458fe2692519efad5a46b88953d1d0228aa8a81c6d43a14f7167cac4e2"}

https://github.com/anthropics/skills|3b3fad96af16a10759d930941b4520ba0c40edae|doc-coauthoring
  {"version": "3b3fad96af16a10759d930941b4520ba0c40edae",
   "skill_name": "doc-coauthoring", "source_url": "https://github.com/anthropics/skills",
   "resolved_sha": "fd8325cb199c45d53792e9fbc144d72832900c77aa31bc3b781099d5cbe81266",
   "tree_storage_prefix": "skills/sha256-fd8325cb199c45d53792e9fbc144d72832900c77aa31bc3b781099d5cbe81266"}
```

Note both were **already registered** from the earlier #876 install, and this second
install uploaded nothing. That reconfirms #876's cache-hit claim incidentally.

## Link 2: per-phase scoping survives into the event store (PROVEN)

The workflow detail API response carries **no** `skills` field, and neither does the
`workflow_details` projection. The data is in the event store, which is the source of
truth. Parsed from `events.payload` for aggregate `skillproof-research-v1`:

```
workflow-scope skills:
[
  {
    "skill_name": "repo-conventions",
    "source_url": "./skills/repo-conventions",
    "version": "sha256-7df181458fe2692519efad5a46b88953d1d0228aa8a81c6d43a14f7167cac4e2",
    "name_overridden": true
  }
]

per-phase skills:
investigate -> [{"skill_name": "doc-coauthoring", "source_url": "https://github.com/anthropics/skills", "version": "3b3fad96af16a10759d930941b4520ba0c40edae", "name_overridden": true}]
summarize   -> []
```

Exactly the declared divergence, stored per phase.

## Link 3: materialise + `skills add` at provision time (PROVEN)

`syn-api` logs for `exec-3db1801d5a3c`:

```
[19:51:38.161] Creating workspace (id=ab1af1d0-9003-4385-8caf-107f82fd05ce, execution=exec-3db1801d5a3c)
[19:51:51.918] Workspace image signature verified: ghcr.io/agentparadise/omni-agent-workspace@sha256:7b82a14dd65cdd6bdee141a87677055e3110c0cb86d52b33765e6850a773aaea
               Container created (id=ws-da23db28, container=agentic-ws-da23db28)
[19:51:53.018] Running setup phase with secrets (workspace=ab1af1d0-...)
[19:51:54.853] Setup phase complete, transient material cleared (workspace=ab1af1d0-...)
[19:51:54.855] Injected /workspace/AGENTS.md + CLAUDE.md (1 repo(s))
[19:51:55.099] Installed 2 skill(s) for agent claude-code in ab1af1d0-9003-4385-8caf-107f82fd05ce
```

Two facts worth recording: the install lands **after** the setup phase and after
secrets are cleared, and it lands **~3 seconds after container creation**. The first
capture attempt fired on first sight of the container at `19:51:52Z` and saw no
skills directory at all, which is a timing artifact, not a failure. See "Honest gaps".

## Link 4: on-disk install path, per phase (PROVEN, captured live)

### Phase `investigate` (container `agentic-ws-da23db28`, claude harness)

```
$ docker exec agentic-ws-da23db28 sh -lc '...'
=== .syn-skills staging ===
drwxr-xr-x 3 agent agent  96 Aug 22 19:51 doc-coauthoring
drwxr-xr-x 3 agent agent  96 Aug 22 19:51 repo-conventions
=== .claude/skills ===
drwxr-xr-x 3 agent agent 96 Aug 22 19:51 doc-coauthoring
drwxr-xr-x 3 agent agent 96 Aug 22 19:51 repo-conventions
=== .agents/skills ===
ls: cannot access '/workspace/.agents/skills/': No such file or directory
```

Both skills are installed at `/workspace/.claude/skills/`, the claude-harness path.
`/workspace/.agents/skills/` (the codex path) does not exist, which is correct for a
claude phase and is the assertion that `skills list --agent <key>` cannot make.

### Phase `summarize` (container `agentic-ws-b57352f6`, claude harness)

```
$ docker exec agentic-ws-b57352f6 sh -lc '...'
=== .syn-skills ===
drwxr-xr-x 3 agent agent  96 Aug 22 19:52 repo-conventions
=== .claude/skills ===
drwxr-xr-x 3 agent agent 96 Aug 22 19:52 repo-conventions
=== .agents/skills ===
ls: cannot access '/workspace/.agents/skills/': No such file or directory
```

**`doc-coauthoring` is absent.** This is the per-phase isolation claim, proven on a
real execution, at the install path rather than at `skills list`.

### `skills list --json`, phase `summarize`

```json
[
  {
    "name": "repo-conventions",
    "path": "/workspace/.claude/skills/repo-conventions",
    "scope": "project",
    "agents": [
      "Claude Code"
    ]
  }
]
```

### Installed content is the plugin's content, phase `summarize`

```
$ find /workspace/.claude/skills -name SKILL.md
/workspace/.claude/skills/repo-conventions/SKILL.md

$ head -5 /workspace/.claude/skills/repo-conventions/SKILL.md
---
name: repo-conventions
description: House conventions for this repository - commit message shape, branch naming, and where documents live. Use when writing a commit, opening a PR, or deciding where a new document belongs.
---
```

Byte-identical frontmatter to `workflows/examples/starter-plugin/skills/repo-conventions/SKILL.md`.

### `/workspace/skills-lock.json`, phase `summarize`

```json
{
  "version": 1,
  "skills": {
    "repo-conventions": {
      "source": "/workspace/.syn-skills/repo-conventions",
      "sourceType": "local",
      "computedHash": "115b00e7d27b8964878c81e100a263629a44b1a9edd5dfa1baee553a799cc251"
    }
  }
}
```

This file is written by the vendored `skills` CLI, not by Syntropic137. It records
`.syn-skills/<name>` as the install source, which pins the staging-to-installed hop.
One skill entry, matching the phase declaration.

## Link 5: deterministic harness surface, pre-inference (PROVEN, with a caveat)

The claude stream-json `system`/`init` event was emitted (the API logged its key set,
including `skills`), but the API does not log the array values and the stdout stream
is not persisted:

```
System event: subtype=init keys=['type', 'subtype', 'cwd', 'session_id', 'tools',
'mcp_servers', 'model', 'permissionMode', 'slash_commands', 'apiKeySource',
'claude_code_version', 'output_style', 'agents', 'skills', 'plugins',
'analytics_disabled', 'uuid', 'memory_paths', 'fast_mode_state']
```

What **is** persisted is the harness-rendered skill listing that Claude Code injects
into context as an `attachment` before the first inference turn. It comes from the
same harness registry that populates `skills[]`, and it is model-independent: the
model did not produce it and could not have. Captured from the session store
(`http://100.112.178.5:18090/v1/sessions/<id>/raw`).

Phase `investigate`, session `43cd5232-1948-49af-be66-ee73ffcc6d4e`:

```
- doc-coauthoring: Guide users through a structured workflow for co-authoring
  documentation. Use when user wants to write documentation, proposals, technical
  specs, decision docs, or similar structured content. ...
- repo-conventions: House conventions for this repository - commit message shape,
  branch naming, and where documents live. Use when writing a commit, opening a PR,
  or deciding where a new document belongs.
- init: Initialize a new CLAUDE.md file with codebase documentation
```

Phase `summarize`, session `e7feb544-eab2-4d22-8c7a-b490c4755edc`:

```
- repo-conventions: House conventions for this repository - commit message shape,
  branch naming, and where documents live. Use when writing a commit, opening a PR,
  or deciding where a new document belongs.
- init: Initialize a new CLAUDE.md file with codebase documentation
```

Occurrence counts across each full raw session:

| session | `repo-conventions` | `doc-coauthoring` |
|---|---|---|
| `investigate` | 1 | 1 |
| `summarize` | 1 | **0** |

The listing is alphabetical, so `doc-coauthoring` sat immediately before
`repo-conventions` in phase 1 and is simply gone in phase 2. Both skills declare a
`description` and neither sets `userInvocable: false`, so neither is filtered out of
the harness listing.

## Honest gaps

Stated plainly, because a gap reported is worth more than a claim that cannot be checked.

1. **The literal `skills[]` array from the `system`/`init` stream-json event was not
   captured.** The API parses that event and logs only its key names; the raw stdout
   stream is not persisted anywhere, and the session store holds Claude Code's on-disk
   conversation log, which has no `init` event. What is presented above is the harness's
   rendered skill listing from the same registry, injected pre-inference. That is
   strong model-independent evidence for the same underlying registry, but it is not
   byte-for-byte the `skills[]` array. Closing this properly needs the engine to log
   the parsed `skills[]` values, which is a one-line observability change and worth
   filing.

2. **`skills list --json` was captured for phase `summarize` only.** The phase
   `investigate` container was destroyed before that command ran; the first capture
   poller fired 3 seconds too early, before the install landed, and by the time the
   timing was corrected phase 1 was over. Phase `investigate`'s directory listing
   (both skills under `/workspace/.claude/skills/`) was captured live and is the
   load-bearing evidence anyway, since `skills list --agent <key>` does not filter
   and the path is the real assertion.

3. **Codex phases were not exercised.** Every phase in this plugin is claude, so
   `/workspace/.agents/skills/` was only ever proven **absent**, never proven to be
   the correct install target for a codex phase. The harness key mapping
   (`claude -> claude-code`, `codex -> codex`, `gemini -> gemini-cli`) is unit-tested
   but the codex on-disk path is untested end to end.

4. **The interactive/shared-workspace path is a real isolation hole.**
   `WorkspaceProvisionHandler.build_followup_result` never calls
   `_materialize_and_install_skills`. On the shared-interactive tmux path a follow-up
   phase reuses the prior workspace, so it neither gets its own skills installed nor
   has the previous phase's skills removed. Per-phase isolation as proven here holds
   because each headless phase gets a fresh container. It does **not** hold on the
   shared-workspace path. Worth filing separately.

5. **A CLI bug surfaced en route.** `syn workflow run <id>` resolves the workflow
   against `GET /workflows`, which is capped at 20 results. With 22 workflows on this
   stack, `skillproof-research-v1` was invisible and the run failed with
   `No workflow found matching: skillproof-research-v1` even though
   `GET /workflows/skillproof-research-v1` returned 200. The run was driven via the
   API directly instead. Unrelated to skills, but it will bite anyone with more than
   20 workflows. Worth filing.

## Regression test added

The live proof above is a point-in-time observation. To keep it from rotting,
`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_skills_per_phase_isolation.py`
provisions two phases from one workflow through the real `WorkspaceProvisionHandler`
and asserts the negative for phase B: no `doc-coauthoring` in any injected path and no
`skills add` for it.

Before this, every skills test provisioned a single phase. Nothing asserted isolation.

The test was mutation-checked: declaring the phase-only skill at workflow scope makes
it fail with

```
AssertionError: phase-scope skill 'doc-coauthoring' leaked into a phase that does not
declare it: ['.syn-skills/repo-conventions/SKILL.md', '.syn-skills/doc-coauthoring/SKILL.md']
```

## Summary

| Link | Status |
|---|---|
| plugin install registers both skill sources | PROVEN |
| per-phase scoping persisted to the event store | PROVEN |
| resolve + materialise into the container | PROVEN |
| `skills add` executed for the phase's harness | PROVEN (via API log + on-disk result) |
| installed at the claude harness path, not just staged | PROVEN |
| **skill on phase A absent from phase B** | **PROVEN, live, both containers** |
| skill visible to the harness pre-inference | PROVEN via rendered listing; literal `skills[]` array NOT captured |
| codex harness path end to end | NOT PROVEN |
| isolation on the shared-interactive path | KNOWN BROKEN by inspection, not exercised |
