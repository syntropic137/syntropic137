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

# Phases - the building blocks
phases:
  - id: phase-1
    name: Research Phase
    order: 1
    execution_type: sequential  # sequential|parallel|human_in_loop
    description: Gather information
    
    # I/O artifact types
    input_artifacts: []
    output_artifacts:
      - research_summary
      - source_references
    
    # Agent configuration
    prompt_template: research_v1
    max_tokens: 4096
    timeout_seconds: 300

  - id: phase-2
    name: Analysis Phase
    order: 2
    execution_type: sequential
    input_artifacts:
      - research_summary
    output_artifacts:
      - analysis_report
```

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

