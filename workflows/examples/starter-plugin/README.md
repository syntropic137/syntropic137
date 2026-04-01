# Starter Plugin

A **multi-workflow plugin** example — bundles multiple workflows with shared phases.

## Structure

```
starter-plugin/
├── syntropic137.yaml           # Plugin manifest (name, version, author)
├── workflows/
│   ├── research/
│   │   ├── workflow.yaml       # Research workflow definition
│   │   └── phases/
│   │       └── investigate.md
│   └── pr-review/
│       ├── workflow.yaml       # PR review workflow definition
│       └── phases/
│           └── review.md
├── phase-library/              # Shared phases across all workflows
│   └── summarize.md
└── README.md
```

The `syntropic137.yaml` manifest provides package metadata. The `phase-library/`
directory contains phases that any workflow can reference using the `shared://` prefix:

```yaml
# In any workflow.yaml:
phases:
  - id: summarize
    prompt_file: shared://summarize    # → phase-library/summarize.md
```

Shared phase content is resolved at install time (copy-on-create) — updating the
library only affects future installs, not already-installed workflows.

## Workflows

- **Starter Research** — Quick research with a shared summarize phase
- **Starter PR Review** — Automated code review with a shared summarize phase

## Usage

```bash
# Install all workflows in the plugin
syn workflow install ./starter-plugin/

# Run a specific workflow
syn workflow run starter-research-v1 --task "Compare event sourcing frameworks"
syn workflow run starter-pr-review-v1 --task "#42"
```

## Learn More

See [docs/workflow-packages.md](../../../docs/workflow-packages.md) for the full format specification.
