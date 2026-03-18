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

    # Prompt template — the Claude Code command
    # Use $ARGUMENTS for the primary task, {{variable}} for named inputs
    prompt_template: |
      You are a research assistant.

      ## Your Task
      $ARGUMENTS

      ## How to Approach This
      1. Identify key areas of interest
      2. Gather context from {{topic}}
      3. Output structured findings

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

