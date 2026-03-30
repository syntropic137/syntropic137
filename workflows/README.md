# Workflow Definitions

This directory contains YAML workflow definitions that can be seeded into the system.

## Structure

```
workflows/
├── README.md           # This file
├── examples/           # Example workflow templates
│   └── research.yaml
├── schemas/            # JSON schemas for validation (auto-generated)
└── custom/             # Custom workflows (gitignored for local dev)
```

## Workflow YAML Schema

```yaml
# Workflow metadata
id: unique-workflow-id        # Required, unique identifier
name: My Workflow             # Required, human-readable name
description: What this does   # Optional

# Classification
type: research                # research|planning|implementation|review|deployment|custom
classification: standard      # simple|standard|complex|epic

# Repository context (optional, can be overridden at runtime)
repository:
  url: https://github.com/org/repo
  ref: main

# Input declarations — what this workflow expects at runtime
# Maps to the --task flag and --input key=value pairs in the CLI
inputs:
  - name: task                # Special: substituted for $ARGUMENTS in prompts
    description: "What to work on (issue body, topic, etc.)"
    required: true
  - name: topic               # Additional named inputs
    description: "Short topic label"
    required: false
    default: "general"

# Phases - the building blocks (each phase = one Claude Code command)
phases:
  - id: phase-1
    name: Research Phase
    order: 1
    execution_type: sequential  # sequential|parallel|human_in_loop
    description: Gather information
    argument_hint: "[task-description]"  # Hint for what $ARGUMENTS expects
    model: sonnet                        # Per-phase model override (optional)

    # I/O artifact types
    input_artifacts: []
    output_artifacts:
      - research_summary
      - source_references

    # Agent configuration
    max_tokens: 4096
    timeout_seconds: 300

    # Prompt — inline OR external file (mutually exclusive)
    # Use $ARGUMENTS for the primary task, {{variable}} for named inputs
    prompt_template: |
      You are a research assistant.

      ## Your Task
      $ARGUMENTS

      ## How to Approach This
      1. Identify key areas of interest
      2. Gather context from {{topic}}
      3. Output structured findings

    # OR reference an external .md file instead of inline prompt_template:
    # prompt_file: prompts/research.md  # Resolved relative to this YAML file

  - id: phase-2
    name: Analysis Phase
    order: 2
    execution_type: sequential
    argument_hint: "[task-description]"
    input_artifacts:
      - research_summary
    output_artifacts:
      - analysis_report
    prompt_template: |
      Analyze the research findings.

      ## Original Task
      $ARGUMENTS

      ## Previous Phase Output
      {{phase-1}}
```

### Prompt Substitution

Workflow prompts support two substitution patterns that coexist:

| Pattern | Source | Example |
|---------|--------|---------|
| `$ARGUMENTS` | The `task` field (CLI `--task` flag) | `$ARGUMENTS` → `"Investigate auth middleware"` |
| `{{variable}}` | Named inputs (CLI `--input key=value`) | `{{topic}}` → `"authentication"` |
| `{{phase-id}}` | Output from a previous phase | `{{phase-1}}` → *(phase 1 artifact content)* |

Built-in variables: `{{execution_id}}`, `{{workflow_id}}`, `{{repo_url}}`

## External Prompt Files

Instead of inlining prompts in YAML, phases can reference external `.md` files via `prompt_file`. This uses the same format as Claude Code commands — optional YAML frontmatter between `---` delimiters, followed by the prompt body.

```yaml
# In your workflow YAML:
phases:
  - id: discovery
    name: Discovery
    order: 1
    prompt_file: prompts/discovery.md  # Resolved relative to this YAML file
```

```markdown
<!-- prompts/discovery.md -->
---
model: sonnet
argument-hint: "<research topic or question>"
allowed-tools: Bash, Read, Grep, Glob
max-tokens: 4096
timeout-seconds: 300
---

You are a research assistant conducting initial exploration.

## Your Task
$ARGUMENTS

## How to Approach This
1. Identify key areas of interest
2. Gather relevant context from the codebase
3. Define 3-5 research questions

Output a structured research scope with your initial questions.
```

### Frontmatter Keys

| Frontmatter Key | Maps To | Type |
|-----------------|---------|------|
| `model` | `model` | string |
| `argument-hint` | `argument_hint` | string |
| `allowed-tools` | `allowed_tools` | comma-separated string or YAML list |
| `max-tokens` | `max_tokens` | integer |
| `timeout-seconds` | `timeout_seconds` | integer |

### Merge Precedence

YAML phase config always overrides `.md` frontmatter. Frontmatter values are used only when the YAML does not set that field. This means the `.md` file provides sensible defaults, while the workflow YAML can override any of them per-phase.

### Rules

- `prompt_template` and `prompt_file` are **mutually exclusive** — set one or the other
- `prompt_file` paths are resolved relative to the YAML file's directory (or an explicit `base_dir`)
- Missing `.md` files produce a clear `FileNotFoundError` at load time
- `$ARGUMENTS` and `{{variable}}` substitutions work identically in both inline and external prompts
- Resolution happens at **load/seed time** — the domain model always receives a resolved prompt string

## Seeding Workflows

```bash
# Seed all workflows from the examples directory
syn workflow seed

# Seed from a specific directory
syn workflow seed --dir workflows/custom

# Seed a single workflow file
syn workflow seed --file workflows/examples/research.yaml

# Validate without seeding (dry-run)
syn workflow seed --dry-run
```

## Creating Custom Workflows

1. Copy an example from `workflows/examples/`
2. Modify the phases and configuration
3. Place in `workflows/custom/` (gitignored) or create a PR to add to `examples/`
4. Run `syn workflow seed` to load into the system

