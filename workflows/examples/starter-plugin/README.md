# Starter Plugin

A **multi-workflow plugin** example. It bundles multiple workflows, shares a phase
between them, and declares agent **skills** from both supported sources.

Copy this directory as the starting point for your own plugin.

## Structure

```
starter-plugin/
├── syntropic137.yaml           # Plugin manifest (name, version, author)
├── skills/
│   └── repo-conventions/
│       └── SKILL.md            # VENDORED skill: ships inside the plugin
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
directory contains phases that any workflow can reference using the `shared://`
prefix:

```yaml
# In any workflow.yaml:
phases:
  - id: summarize
    prompt_file: shared://summarize    # -> phase-library/summarize.md
```

Shared phase content is resolved at install time (copy-on-create), so updating the
library only affects future installs, not already-installed workflows.

## Skills

`skills:` is accepted at **workflow scope** (applies to every phase) and at
**phase scope** (applies to that phase only). The two lists merge. Both sources
are demonstrated here:

| Source | Declared as | Pinned by |
|---|---|---|
| Vendored (in the plugin) | `./skills/repo-conventions` | sha256 of the directory's file tree, computed by the CLI at install |
| External (a git repo) | `anthropics/skills/doc-coauthoring@<sha>` | the git ref you write, cloned by the CLI at install |

Rules worth knowing before you copy this:

- **Refs must be pinned.** `@latest` is rejected by design. A tag, a branch, or a
  commit sha is fine. `anthropics/skills` publishes no tags, so this example pins
  a commit sha.
- **A vendored skill needs no version.** Edit a byte in `SKILL.md` and the next
  install registers a new identity; change nothing and the next install uploads
  nothing, because the content hash is the cache.
- **Identity is `(source_url, version, skill_name)`.** The same vendored skill
  declared by two workflows registers once.
- **A shorthand ref has three segments:** `org/repo/skill-name@version`. Two
  segments is the `claude_plugins:` shape and is rejected with a corrective error.
- **A phase that declares skills fails if they cannot be installed.** It never
  silently runs without them.

Per-phase divergence in this plugin, which is what makes isolation observable:

| Workflow | Phase | Skills it gets |
|---|---|---|
| `starter-research-v1` | `investigate` | `repo-conventions` (workflow scope) + `doc-coauthoring` (phase scope) |
| `starter-research-v1` | `summarize` | `repo-conventions` only |
| `starter-pr-review-v1` | `review` | `repo-conventions` (phase scope) |
| `starter-pr-review-v1` | `summarize` | none |

Every phase sets `model: haiku` so that running this example as a validation
fixture stays cheap.

## Workflows

- **Starter Research**: quick research with a shared summarize phase
- **Starter PR Review**: automated code review with a shared summarize phase

## Usage

```bash
# Install all workflows in the plugin (registers the declared skills first)
syn workflow install ./starter-plugin/

# Inspect what got registered
syn skill list
syn skill show repo-conventions

# Run a specific workflow
syn workflow run starter-research-v1 --task "Compare event sourcing frameworks"
syn workflow run starter-pr-review-v1 --task "#42"
```

A second `syn workflow install` re-prints each skill as `already registered` and
uploads nothing.

## Learn More

See [docs/workflow-packages.md](../../../docs/workflow-packages.md) for the full
format specification.
