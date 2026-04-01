# Research Package

A **single workflow package** example — the simplest distribution format.

## Structure

```
research-package/
├── workflow.yaml       # Workflow definition (2 phases)
├── phases/
│   ├── discovery.md    # Phase 1: explore the topic
│   └── synthesis.md    # Phase 2: synthesize findings
└── README.md
```

This is a single workflow package — it has `workflow.yaml` at the root with phase
prompts in `phases/`. Each `.md` file uses YAML frontmatter for model configuration
and the body for the prompt text.

## Usage

```bash
# Install
syn workflow install ./research-package/

# Run
syn workflow run research-package-v1 --task "Investigate event sourcing patterns"
```

## Phases

- **Discovery** — Explores the topic, identifies key areas and sources
- **Synthesis** — Combines findings into a structured report with recommendations

## Learn More

See [docs/workflow-packages.md](../../../docs/workflow-packages.md) for the full format specification.
