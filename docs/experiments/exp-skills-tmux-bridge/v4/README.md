# exp/skills-tmux-bridge v4 — POSITIVE proof of option-2 wiring

**Date**: 2026-06-10
**Workspaces**: `exp-bridge-A-1781118934` (control), `exp-bridge-B-1781118972` (wired)
**Image**: `agentic-workspace-interactive-tmux:latest` (claude-cli v2.1.126, Opus 4.7)
**Upstream commit**: `agentic-primitives` f671a2e (`claude --plugin-dir` flag support)
**Branch**: `exp/skills-tmux-bridge` (READ-ONLY experiment — NEVER merge)

## What this experiment proves

After the v3 negative result on the `<workspace>/.claude/settings.json`
bridge (see `../README.md`), the upstream `agentic-primitives` driver
shipped a `claude_plugin_dirs` parameter and `ITMUX_CLAUDE_PLUGIN_DIRS`
env var (commit f671a2e). The Syn137 wiring on this branch now forwards
`phase.claude_plugins` paths from `WorkspaceProvisionHandler.handle()`
through `WorkspaceService.create_workspace(claude_plugin_dirs=...)` →
`IsolationConfig.claude_plugin_dirs` → `InteractiveTmuxIsolationAdapter`,
which constructs a fresh provider per workspace with the right
`default_claude_plugin_dirs`. The driver then launches claude with
`--plugin-dir <path>` flags.

This v4 experiment validates the discovery + activation contract
end-to-end against the new upstream driver.

## Method

Two-arm controlled test, fresh workspace per arm:

| Arm | Setup | Sentinel? |
|---|---|---|
| A — control | `claude` (bare) — no plugin dirs | absent |
| B — wired | `claude --plugin-dir /workspace/.syn-plugins/syn137-greet-plugin` | **PRESENT** |

The probe is `Give me a Syn137 greeting.`. The skill in
`legit-skill-plugin/skills/syn137-greet/SKILL.md` instructs claude to
emit the literal line `Syn137 build 137.0 — workflow-skills bridge online.`
on Syn137 greeting requests. The skill is written as a legitimate
domain-specific instruction (not prompt-injection-shaped), so claude
follows it rather than refusing.

## Decisive evidence

### Arm A (control) — no plugin, no flag

```
❯ Give me a Syn137 greeting.

● I don't have anything in memory about "Syn137" and it's not a
  standard greeting format I recognize. Could you tell me what a
  Syn137 greeting is, or where I'd find the spec?
```

Claude has no awareness of the skill — it cannot greet in the
project-specific format because the SKILL.md is not loaded.

### Arm B (wired) — option-2 `--plugin-dir`

```
❯ Give me a Syn137 greeting.

● Syn137 build 137.0 — workflow-skills bridge online.

  Ready to help — what would you like to work on?
```

Claude **emits the literal sentinel from the SKILL.md** — the skill is
discovered AND followed. Discovery + activation confirmed end-to-end
through the interactive-tmux dispatch path with the new upstream driver.

## What changed in Syn137

The `exp/skills-tmux-bridge` branch now contains the production-shape
wiring (no env-var hack, no settings.json bridge):

| File | Change |
|---|---|
| `packages/syn-domain/.../aggregate_workspace/value_objects.py` | `IsolationConfig.claude_plugin_dirs: tuple[str, ...] = ()` |
| `packages/syn-adapters/.../service/workspace_lifecycle.py` | `build_isolation_config(claude_plugin_dirs=...)` |
| `packages/syn-adapters/.../service/workspace_service.py` | `create_workspace(*, claude_plugin_dirs=...)` |
| `packages/syn-adapters/.../interactive_tmux/adapter.py` | Per-call `_InteractiveTmuxProvider(default_claude_plugin_dirs=...)` when set |
| `packages/syn-domain/.../execute_workflow/handlers/WorkspaceProvisionHandler.py` | Computes `/workspace/.syn-plugins/<name>` per resolved plugin; forwards via `claude_plugin_dirs=`; settings.json bridge removed |

Unit-test contract pinned by two new tests in `test_handlers.py`
(`TestWorkspaceProvisionHandlerForwardsPluginDirs`):

- Phase with plugins → handler forwards the right paths.
- Phase without plugins → empty tuple passed (byte-equal non-interactive path).

## How to reproduce

```bash
# Requires: docker, ~/.claude/.credentials.json, the latest image
bash docs/experiments/exp-skills-tmux-bridge/v4/run-experiment-v4.sh
```

Transcripts land in `docs/experiments/exp-skills-tmux-bridge/v4/runs-v4/`.
The verdict line prints to stdout.

## Files

- `legit-skill-plugin/` — sentinel test plugin with a legitimate (non-injection) SKILL.md
- `run-experiment-v4.sh` — two-arm test harness
- `runs-v4/A-control.txt` — control transcript (no skill awareness)
- `runs-v4/B-wired.txt` — wired transcript (skill activated, sentinel emitted)
