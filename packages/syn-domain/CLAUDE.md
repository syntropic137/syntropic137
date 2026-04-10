---
description: Workflow authoring standard for syn-domain — phase files, artifacts, and plugin structure
globs: ["**/workflows/**", "**/phases/**", "**/workflow.yaml", "**/syntropic137-plugin.json"]
alwaysApply: false
---

# Workflow Authoring — syn-domain

This file covers the standard for authoring Syntropic137 workflow plugins and phase files. When building or reviewing workflows, commands, or skills in this area, follow this guide.

## Claude Commands and Skills Docs

When creating Claude commands or skills here, always WebFetch the latest docs first:

- Commands: https://code.claude.com/docs/en/commands.md
- Skills: https://code.claude.com/docs/en/skills.md
- Hooks: https://code.claude.com/docs/en/hooks.md
- Settings and tools: https://code.claude.com/docs/en/settings.md

**Rule: WebFetch the relevant doc above before authoring any command, skill, or hook.**

---

## Phase File Standard

Workflow phase files (`phases/*.md`) follow the Claude command standard. Each phase is one command invocation. Treat them identically to Claude custom slash commands.

### Format

```md
---
model: sonnet|haiku
allowed-tools: bash, git, read[, edit]
description: One-line description of what this phase does
---

# Phase Name

Brief purpose statement. References `Variables` and `Workflow` sections.

## Variables

DYNAMIC_VAR: {{input_name}}
STATIC_VAR: value
PREVIOUS_OUTPUT: {{prev_phase_id}}

## Workflow

1. Numbered step with exact commands
2. Next step

## Report

Write output to `artifacts/output/<name>.md` with this structure:
[describe exact format]
```

### Rules

- **Variables section required:** list every `{{variable}}` used, dynamic first, static second
- **Previous phase input:** reference via `{{phase_id}}` variable substitution — no hardcoded paths
- **Output:** write to `artifacts/output/<name>.md` — relative path, workspace root is platform-injected
- **Model:** haiku for lightweight passes (context gather, verify), sonnet for analysis and implementation
- **Token-efficient:** no "you are an AI" preamble, no redundant context
- **Punctuation:** prefer `:` and `,` over `-` and em dashes

---

## Artifact System

Each phase runs in an ephemeral Docker workspace:

```
/workspace/
├── artifacts/
│   ├── input/    ← previous phase outputs, injected by platform as {phase_id}.md
│   └── output/   ← write deliverables here — only path collected
└── repos/        ← clone repos here
```

Previous phase content is available two ways:
- Variable substitution: `{{phase_id}}` is replaced inline with the phase's output
- File: `artifacts/input/{phase_id}.md` (platform-injected, workspace prompt explains paths)

Phase files use relative paths only. The workspace root is a platform concern.

### Declaring artifacts in workflow.yaml

```yaml
phases:
  - id: analyze
    input_artifacts: []         # phase IDs whose outputs to inject
    output_artifacts:
      - findings                # names this phase writes to artifacts/output/
```

---

## Ephemeral Phase Constraint

State does not survive between phases except via:

- **Artifacts:** written to `artifacts/output/`, available to next phase via `{{phase_id}}`
- **GitHub:** comments, reviews, releases posted via `gh`
- **Git push:** if a phase edits files, it MUST commit and push in the same phase

You cannot edit in phase 2 and push in phase 3.

---

## `--repo` Flag Rule

All `gh` CLI subcommands MUST include `--repo {{repository}}`. The workspace git remote is not reliable.

`gh api` calls with `repos/` in the URL path are fine as-is.

---

## Plugin Structure

```
plugins/
└── my-plugin/
    ├── syntropic137-plugin.json    # name, version, description, author, license, repository
    ├── README.md
    └── workflows/
        └── my-workflow/
            ├── workflow.yaml       # id, inputs, phases (with input/output_artifacts)
            ├── triggers.json       # GitHub event triggers and input_mapping
            └── phases/
                ├── phase-one.md
                └── phase-two.md
```

### workflow.yaml inputs

```yaml
inputs:
  - name: pr_number
    description: "Pull request number"
    required: true
  - name: base_branch
    description: "Base branch"
    required: false
    default: "main"
```

---

## Canonical Source

The marketplace repo (`syntropic137-marketplace`) is the reference implementation for plugin authoring. Its `CLAUDE.md` and the `.claude/commands/workflow-phase.md` meta-command are kept in sync with this standard.
