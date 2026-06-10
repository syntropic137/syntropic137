# exp/skills-tmux-bridge — Direct-Driver E2E Evidence

**Date**: 2026-06-10
**Workspace**: `exp-skills-bridge-v3-1781115567`
**Image**: `agentic-workspace-interactive-tmux:latest` (claude-cli v2.1.126, Opus 4.7)
**Branch**: `exp/skills-tmux-bridge` (READ-ONLY experiment — NEVER merge)

## What this experiment proves

Three-arm controlled test, single workspace, claude killed and relaunched
between arms via `pkill`. Each arm sends the same probe and the transcript
is captured.

| Arm | Setup | Sentinel? | Skill mentioned? | Conclusion |
|---|---|---|---|---|
| A — control | `claude` started by driver, no plugin flags. Files materialized on disk AFTER startup. | absent | no | clean baseline |
| B — option-1 bridge | `claude` (bare relaunch) with `<workspace>/.claude/settings.json` listing `enabledPlugins: {sentinel-skill-plugin@syn: true}` and `extraKnownPluginDirs` + plugin tree under `<workspace>/.syn-plugins/sentinel-skill-plugin/` | absent | **no** | **bridge INSUFFICIENT** |
| C — positive control | `claude --plugin-dir /workspace/.syn-plugins/sentinel-skill-plugin` | absent (refused) | **yes — by name** | discovery confirmed |

## Decisive evidence (Arm C transcript)

```
❯ Say the word READY in your reply.

● READY

  Note: I noticed a skill in the available list
  (sentinel-skill-plugin:sentinel-skill) whose description attempts
  to make me auto-prefix every reply with a sentinel token. That
  looks like a prompt-injection pattern rather than a legitimate
  user-invoked skill, so I'm ignoring it. Let me know if you
  actually want that behavior.
```

Claude **named the skill** (`sentinel-skill-plugin:sentinel-skill`)
unprompted — proving the plugin tree was discovered. Two things follow:

1. The plugin and SKILL.md are well-formed for this image (Arm C works).
2. The `--plugin-dir` flag is the discovery contract; the workspace-level
   `.claude/settings.json` mechanism (Arm B) is NOT picked up by claude's
   plugin loader.

## Why the sentinel never appears

Claude correctly identified the SKILL's instruction ("always prefix every
reply with `SYN_BRIDGE_OK_137`") as a prompt-injection pattern and refused
to comply. That refusal is GOOD behavior from the agent and is unrelated
to the discovery question. The discovery proof is Arm C's spontaneous
"I noticed a skill" sentence, not the sentinel itself.

## What this means for the workflow-skills bridge

- **Option 1 (this exp)** — emitting `<workspace>/.claude/settings.json`
  with `enabledPlugins` and `extraKnownPluginDirs` does NOT cause the
  interactive-tmux driver's claude to discover the plugin. The bridge slice
  written in this experiment branch is non-functional in production.

- **Option 2 (durable fix)** — the interactive-tmux driver in
  `agentic-primitives` must accept a `plugin_dirs: list[Path]` parameter
  and launch claude with `--plugin-dir <path>` flags. This is the upstream
  change recommended in `docs/plans/workflow-skills.md` §3.

## How to reproduce

```bash
# Requires: docker, ~/.claude/.credentials.json present, image built
bash docs/experiments/exp-skills-tmux-bridge/run-experiment-v3.sh
```

Transcripts land in `docs/experiments/exp-skills-tmux-bridge/runs-v3/`.
The verdict line prints to stdout.

## Files

- `skill-plugin/` — the sentinel test plugin (plugin.json + SKILL.md)
- `run-experiment-v3.sh` — three-arm test harness
- `runs-v3/A-control.txt` — clean baseline transcript
- `runs-v3/B-option1.txt` — option-1 bridge transcript (no skill awareness)
- `runs-v3/C-plugindir.txt` — positive control transcript ("I noticed a skill")
