# ADR-043: Git Hook Event Pipeline — Real Git Hooks via Tool Result Scanning

## Status

**Accepted** — 2026-02-19
**Updated** — 2026-02-19 (clarified actual event flow after live debugging)

## Context

AEF needs to record git operations (commits, pushes, merges) that an agent
performs during a session — with real metadata: commit SHA, branch, message,
files changed, token estimates.

### What We Had Before (Wrong)

The original implementation tried two hacks, both rejected:

1. **Claude Code `PreToolUse` stream parsing** — inspected the `tool_input`
   JSON for `Bash` tool calls, looked for `git commit` / `git push` commands,
   and synthesised a git event from the command text. This is unreliable (the
   agent might use `git -C path commit` or shell aliases), produces no real
   metadata (no SHA, no files changed), and conflates "tool called" with "tool
   succeeded".

2. **Parsing Claude's stream-json** — similar problem; observes intent, not
   outcome.

### What We Needed

Real git hooks (`post-commit`, `pre-push`, etc.) fire *after* the operation
succeeds and have access to `git log`, `git diff --shortstat`, etc. This is the
only way to get correct, post-facto metadata.

## Decision

**Use real git hooks installed globally in the workspace container. Hooks emit
JSONL to stderr; Claude Code captures this as part of the Bash tool's output and
packages it in the stream-json `tool_result`. WorkflowExecutionEngine scans each
`tool_result` content string for embedded JSONL lines.**

### Actual Event Flow (verified against live session data)

```
Claude Code runs Bash tool: git commit -m "..."
    │
    ├─► git runs post-commit hook
    │       │
    │       └─► EventEmitter(output=sys.stderr).git_commit(sha, branch, ...)
    │                │
    │                └─► JSONL written to hook's stderr
    │                         │
    │                         └─► propagates up through git's stderr
    │                                  │
    │                                  └─► captured by Claude Code as Bash tool stderr
    │
    └─► Claude Code packages Bash stdout + stderr as tool_result content:
            {"type":"user","message":{"content":[{
              "type":"tool_result",
              "content":"[abc1234] feat: ...\n5 files changed\n{\"event_type\":\"git_commit\",...}"
            }]}}
            │
            └─► emitted as a stream-json line to docker exec stdout

AgenticEventStreamAdapter.stream() reads each line from the docker exec pipe
    │
    └─► WorkflowExecutionEngine line loop:
            │
            ├─► parse_jsonl_line(raw_line) → None (line has "type", not "event_type")
            │
            └─► stream-json branch: cli_type == "user", item.type == "tool_result"
                    │
                    ├─► extract tool_content string
                    │
                    └─► scan each line of tool_content for parse_jsonl_line() hits
                              │
                              └─► {"event_type": "git_commit"} found
                                       │
                                       └─► _record_observation("git_commit", {sha, branch, ...})
                                                │
                                                └─► TimescaleDB → SessionDetail.tsx timeline
```

### Why stderr=STDOUT on docker exec?

`stderr=STDOUT` in `AgenticEventStreamAdapter.stream()` captures any stderr emitted
**directly** by the claude CLI process (not by its subprocesses, which go through
stream-json packaging). This is a safety net for edge cases (internal Claude errors,
future tool types that may bypass packaging). It does NOT directly carry git hook
JSONL — that arrives via the tool_result path above. Do not revert to `PIPE`.

### Components and Their Roles

#### 1. Git hooks (`plugins/observability/hooks/git/`)

- `post-commit` — emits `git_commit` with sha, branch, message, files_changed,
  insertions, deletions, token estimates
- `pre-push` — emits `git_push` with remote, branch
- (post-merge, post-rewrite — future)

Hooks emit to **stderr** (not stdout). Claude Code captures hook subprocess
stdout into the `hook_response` stream-json event; using stderr bypasses that
capture and sends events directly to the docker exec pipe where the engine is
the sole consumer.

#### 2. Global hook installation (`entrypoint.sh`)

```bash
GIT_HOOKS_DIR=".../observability/hooks/git"
git config --global core.hooksPath "${GIT_HOOKS_DIR}"
```

`core.hooksPath` makes git use this directory for *all* repos in the container,
including repos the agent clones mid-task. Without this, hooks only fire in
repos that have their own `.git/hooks/` scripts, which freshly cloned repos
never do.

#### 3. stderr merge (`AgenticEventStreamAdapter.stream()`)

```python
proc = await asyncio.create_subprocess_exec(
    *exec_cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,   # ← critical
)
```

`stderr=STDOUT` merges the container's stderr into the stdout pipe. This is the
only place where the engine reads the stream. Using `stderr=PIPE` or
`stderr=DEVNULL` silently discards all hook events.

**There are two docker exec implementations. Both must use `stderr=STDOUT`:**

| File | Context |
|------|---------|
| `packages/syn-adapters/.../workspace_backends/agentic/adapter.py` | Dashboard / workspace service (production path) |
| `lib/agentic-primitives/.../agentic_isolation/providers/docker.py` | agentic_isolation library |

#### 4. Event discrimination (`parse_jsonl_line()`)

```python
# Hook events: {"event_type": "git_commit", ...}  → parse_jsonl_line returns dict
# Claude json:  {"type": "assistant", ...}          → parse_jsonl_line returns None
```

`parse_jsonl_line()` checks for the `"event_type"` key. Claude's stream-json
uses `"type"`, so the two sources are unambiguous and require no heuristics.

#### 5. Hook data storage (`WorkflowExecutionEngine`)

```python
_hook_data = {
    **(enriched.get("context") or {}),
    **(enriched.get("metadata") or {}),
}
```

Both `context` and `metadata` dicts from the enriched event are merged into the
stored data. **Do not use only `context`** — git-specific fields like `sha`,
`branch`, `message`, `files_changed`, `insertions`, `deletions` may be in
either dict depending on the emitter version.

## Rejected Alternatives

### Claude Code `PreToolUse` hook inference

Reconstruct git events from `tool_name=Bash, tool_input="git commit -m ..."`.

**Rejected:** Observes intent, not outcome. No SHA. Fragile against command
variations. Conflates attempt with success.

### Parsing Claude stream-json for git commands

Same as above with an extra parsing step.

**Rejected:** Same reasons.

### Writing hook events to stdout

Have hooks emit to stdout instead of stderr.

**Rejected:** Git runs hooks as subprocesses; both stdout and stderr end up as
part of the git command's output, which Claude Code captures for the Bash tool
result. Whether we use stdout or stderr, the JSONL arrives embedded in the
tool_result. The distinction matters for Claude Code hooks (PreToolUse/PostToolUse)
where stdout is intercepted differently — for git hooks running inside a Bash
call the channel is irrelevant to the tool_result packaging. Either works, but
stderr is conventional for diagnostic/observability output and avoids any future
confusion with tool stdout parsing.

### Per-repo `.git/hooks/` installation

Install hooks in each repo after cloning.

**Rejected:** Requires knowing when a repo is cloned and running an install
step. `core.hooksPath` is simpler and works automatically for all repos.

## Consequences

### Positive

- Real metadata: SHA, branch, files changed, token estimates
- Events fire only on success (post-commit, not pre-commit)
- Zero inference: no parsing of command text
- Works for all repos the agent touches, including mid-task clones
- Claude Code tool calls remain `tool_execution_started` / `tool_execution_completed` — clean separation

### Negative

- `stderr=STDOUT` means any unexpected stderr output from the agent process
  (e.g. Docker warnings) will appear inline in the stream. `parse_jsonl_line()`
  returns `None` for non-JSONL lines so these are silently ignored, but they
  will appear in conversation logs.
- Hooks must be `chmod 755` and present at build time in the workspace image.

### Invariants — Do Not Break

1. **Tool result scanning** in `WorkflowExecutionEngine` — the `cli_type == "user"`
   / `item.type == "tool_result"` branch must scan every line of `tool_content`
   for JSONL events. This is the PRIMARY path for git hook events. Removing this
   scan silently kills git event observability.
2. **`stderr=STDOUT`** in both docker exec stream methods. Captures any stderr
   emitted directly by the claude process. Not the primary path for git events,
   but a critical safety net.
3. **`core.hooksPath`** set in `entrypoint.sh`. Without it, hooks only fire in
   repos that pre-installed them — freshly cloned repos never have `.git/hooks/`.
4. **`_hook_data = {**context, **metadata}`** — both dicts merged, not just
   `context`.
5. **`parse_jsonl_line()` is the sole discriminator** between hook events and
   Claude stream-json. It checks for `"event_type"` key. Do not add ad-hoc checks.

## Related ADRs

- [ADR-022](../../lib/agentic-primitives/docs/adrs/022-git-hook-observability.md) — original git hook design in agentic-primitives (pre-container, file-based)
- [ADR-029](../../lib/agentic-primitives/docs/adrs/029-simplified-event-system.md) — JSONL event system (`agentic_events`)
- [ADR-015](./ADR-015-agent-observability.md) — agent session observability
- [ADR-033](../../lib/agentic-primitives/docs/adrs/033-plugin-native-workspace-images.md) — plugin architecture for workspace images

## Files Implementing This ADR

```
packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py
    AgenticEventStreamAdapter.stream() — stderr=STDOUT (production path)

lib/agentic-primitives/lib/python/agentic_isolation/agentic_isolation/providers/docker.py
    WorkspaceDockerProvider.stream() — stderr=STDOUT (agentic_isolation path)

lib/agentic-primitives/plugins/observability/hooks/git/post-commit
    Emits git_commit to sys.stderr via EventEmitter

lib/agentic-primitives/plugins/observability/hooks/git/pre-push
    Emits git_push to sys.stderr via EventEmitter

lib/agentic-primitives/providers/workspaces/claude-cli/scripts/entrypoint.sh
    git config --global core.hooksPath  (global hook installation)

packages/syn-domain/.../WorkflowExecutionEngine.py
    parse_jsonl_line() call site + _hook_data = {**context, **metadata} merge
```
