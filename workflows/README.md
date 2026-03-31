# Workflow Definitions

This directory contains workflow definitions and example packages for Syntropic137.

## Installing Workflows

The primary way to get workflows into a running Syntropic137 instance:

```bash
# Install from a local package directory
syn workflow install ./examples/research-package/

# Install from a git repository
syn workflow install https://github.com/org/workflow-library
syn workflow install org/workflow-library              # GitHub shorthand
syn workflow install org/workflow-library --ref v2.0   # Specific version

# Validate a package without installing
syn workflow validate ./examples/research-package/

# List installed packages
syn workflow installed
```

## Package Formats

### Single Workflow Package

A self-contained directory with one workflow and its prompt files:

```
my-workflow/
├── workflow.yaml          # Orchestration metadata (phases, inputs, models)
├── phases/
│   ├── discovery.md       # Phase prompt (frontmatter + body)
│   └── synthesis.md
└── README.md
```

See `examples/research-package/` for a working example.

### Multi-Workflow Plugin

A plugin bundling multiple workflows with shared phases:

```
my-plugin/
├── syntropic137.yaml      # Plugin manifest (name, version, author)
├── workflows/
│   ├── research/
│   │   ├── workflow.yaml
│   │   └── phases/*.md
│   └── pr-review/
│       ├── workflow.yaml
│       └── phases/*.md
├── phase-library/         # Shared phases (shared:// prefix)
│   └── summarize.md
└── README.md
```

See `examples/starter-plugin/` for a working example.

### Standalone YAML (Legacy)

Individual `.yaml` files without the package directory structure.
Still supported for backward compatibility with existing examples.

## Creating New Packages

```bash
# Scaffold a single workflow package
syn workflow init ./my-workflow --name "My Workflow" --type research --phases 3

# Scaffold a multi-workflow plugin
syn workflow init ./my-plugin --name "My Plugin" --multi
```

## Workflow YAML Schema

```yaml
id: unique-workflow-id        # Required, unique identifier
name: My Workflow             # Required, human-readable name
description: What this does   # Optional
type: research                # research|planning|implementation|review|deployment|custom
classification: standard      # simple|standard|complex|epic

repository:                   # Optional
  url: https://github.com/org/repo
  ref: main

inputs:
  - name: task                # Special: substituted for $ARGUMENTS in prompts
    description: "What to work on"
    required: true

phases:
  - id: phase-1
    name: Research Phase
    order: 1
    execution_type: sequential  # sequential|parallel|human_in_loop
    argument_hint: "[topic]"
    model: sonnet               # Per-phase model override (optional)
    max_tokens: 4096
    timeout_seconds: 300

    # Prompt — inline OR external file (mutually exclusive)
    prompt_template: |
      You are a research assistant.
      $ARGUMENTS

    # OR reference a file:
    # prompt_file: phases/discovery.md

    # OR reference a shared phase (multi-workflow plugins only):
    # prompt_file: shared://summarize
```

## Prompt Substitution

| Pattern | Source | Example |
|---------|--------|---------|
| `$ARGUMENTS` | The `task` input (CLI `--task` flag) | `$ARGUMENTS` → `"Investigate auth"` |
| `{{variable}}` | Named inputs (CLI `--input key=value`) | `{{topic}}` → `"auth"` |
| `{{phase-id}}` | Output from a previous phase | `{{phase-1}}` → *(phase 1 output)* |

Built-in variables: `{{execution_id}}`, `{{workflow_id}}`, `{{repo_url}}`

## External Prompt Files

Phases can reference `.md` files with optional YAML frontmatter:

```markdown
---
model: sonnet
argument-hint: "[research-topic]"
allowed-tools: Read,Glob,Grep,Bash
max-tokens: 4096
timeout-seconds: 300
---

Your prompt text here. Use $ARGUMENTS and {{variable}} as normal.
```

**Merge precedence:** YAML phase config always overrides `.md` frontmatter.

## Shared Phases (`shared://`)

In multi-workflow plugins, phases can reference shared prompts from `phase-library/`:

```yaml
prompt_file: shared://summarize    # resolves to phase-library/summarize.md
```

Content is resolved at install time (copy-on-create) — no runtime coupling.

## Development: Seeding

## Editing Phases After Creation

Once a workflow is installed, individual phases can be updated via the API or the dashboard UI without re-creating the entire workflow.

### API

```bash
curl -X PUT /api/v1/workflows/{workflow_id}/phases/{phase_id} \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_template": "Updated prompt with $ARGUMENTS",
    "model": "opus",
    "timeout_seconds": 600
  }'
```

Only `prompt_template` is required. Optional fields (`model`, `timeout_seconds`, `allowed_tools`) use **"keep existing" semantics** — omit them or pass `null` to preserve the current value. Pass an explicit empty value (e.g., `"allowed_tools": []`) to clear a field.

### Dashboard

1. Open a workflow's detail page
2. Click a phase in the pipeline visualization
3. Use the editor to modify the prompt (with live markdown preview) and phase configuration
4. Click **Save**

Changes are event-sourced — the original prompt is preserved in the event history and can be replayed.

## Development: Seeding

For local development and testing, workflows can be seeded directly into the event store bypassing the API:

```bash
just seed-workflows              # Seeds from workflows/examples/
just seed-workflows --dry-run    # Validate only
```

This is a **dev-only tool** — not for production use. For production, use `syn workflow install`.

## Full Format Specification

See [docs/workflow-packages.md](../docs/workflow-packages.md) for the complete package format specification, including the `syntropic137.yaml` manifest schema and Claude Code marketplace alignment notes.

## Directory Structure

```
workflows/
├── README.md               # This file
├── examples/
│   ├── research-package/   # Single workflow package example
│   ├── starter-plugin/     # Multi-workflow plugin example
│   ├── research.yaml       # Standalone YAML examples (legacy)
│   ├── implementation.yaml
│   └── prompts/            # Prompt files for standalone examples
└── triggers/               # GitHub trigger workflow definitions
```
