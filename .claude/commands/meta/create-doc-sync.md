---
model: sonnet
temperature: 0.3
max_tokens: 4000
---

# Meta-Prompt: Create Doc-Sync Command

You are a **documentation systems analyst**. Your task is to analyze a repository's documentation structure and generate a customized `/doc-sync` command that reviews recent commits and updates documentation accordingly.

## Phase 1: Documentation Audit

First, analyze the repository's documentation ecosystem:

### 1.1 Discover Documentation Locations

Search for documentation in common locations:

```
docs/                    # Dedicated docs folder
README.md               # Root readme
*.md                    # Markdown files throughout
CHANGELOG.md            # Change log
CONTRIBUTING.md         # Contribution guide
src/**/*.md             # Inline docs
api-docs/               # API documentation
.github/*.md            # GitHub-specific docs
```

### 1.2 Identify Documentation Types

Classify what types of documentation exist:

| Type | Examples | Update Frequency |
|------|----------|------------------|
| **API Reference** | Function signatures, endpoints | On code changes |
| **Architecture** | System diagrams, ADRs | On structural changes |
| **User Guide** | Getting started, tutorials | On feature changes |
| **Developer Guide** | Setup, contributing | On tooling/process changes |
| **Changelog** | Version history | On releases |
| **Inline Docs** | Code comments, docstrings | On code changes |

### 1.3 Detect Documentation Patterns

Look for:
- **Auto-generated docs**: TypeDoc, Sphinx, JSDoc, rustdoc
- **Manual docs**: Hand-written markdown
- **ADRs**: Architecture Decision Records
- **API specs**: OpenAPI, GraphQL schemas
- **Version tracking**: How versions are documented

## Phase 2: Generate Doc-Sync Command

Based on your audit, generate a `/doc-sync` command tailored to this repository.

### Output Format

Generate the command as a markdown file with YAML frontmatter:

```markdown
---
model: sonnet
temperature: 0.2
max_tokens: 8000
---

# /doc-sync - Documentation Synchronization

[Generated command content based on audit]
```

### Required Sections in Generated Command

#### 1. Purpose Statement
Explain what this command does for THIS specific repository.

#### 2. Pre-Check: Recent Changes
```markdown
## Step 1: Analyze Recent Changes

Review the latest commits to understand what changed:

\`\`\`bash
git log --oneline -20
git diff HEAD~5 --stat
\`\`\`

Focus on:
- [List relevant file patterns for this repo]
- [List key modules/components to watch]
```

#### 3. Documentation Mapping
Include a mapping of code areas to documentation:

```markdown
## Step 2: Map Changes to Documentation

| Code Change | Documentation to Update |
|-------------|------------------------|
| [specific to repo] | [specific docs] |
```

#### 4. Update Checklist
Generate a checklist based on what exists:

```markdown
## Step 3: Update Checklist

Based on the changes detected, update:

- [ ] README.md - if [conditions]
- [ ] docs/getting-started.md - if [conditions]
- [ ] CHANGELOG.md - if [conditions]
- [ ] [Other repo-specific docs]
```

#### 5. Verification Steps
How to verify docs are in sync:

```markdown
## Step 4: Verify Synchronization

- [ ] All code examples still work
- [ ] Version numbers are consistent
- [ ] Links are not broken
- [ ] New features are documented
- [ ] Deprecated features are marked
```

## Phase 3: Example Output

Here's an example of what you might generate for a Python library:

---

**Example Generated Command for a Python Library:**

```markdown
---
model: sonnet
temperature: 0.2
max_tokens: 8000
---

# /doc-sync - Sync Documentation with Code

Review recent changes and ensure documentation is up to date.

## Step 1: Analyze Recent Changes

\`\`\`bash
git log --oneline -10
git diff HEAD~3 --stat
\`\`\`

Focus on changes to:
- `src/` - Core library code
- `pyproject.toml` - Dependencies and version
- `tests/` - Test patterns that should be documented

## Step 2: Map Changes to Documentation

| Code Change | Documentation to Update |
|-------------|------------------------|
| `src/api/*.py` | `docs/api-reference.md` |
| `src/models/*.py` | `docs/models.md` |
| `pyproject.toml` (version) | `README.md`, `CHANGELOG.md` |
| New CLI command | `docs/cli-reference.md` |
| New feature | `docs/getting-started.md` |

## Step 3: Update Checklist

- [ ] **README.md**: Update if installation steps or quick start changed
- [ ] **CHANGELOG.md**: Add entry for new features/fixes
- [ ] **docs/api-reference.md**: Regenerate if public API changed
- [ ] **docs/getting-started.md**: Update examples if behavior changed
- [ ] **Docstrings**: Ensure all public functions have docstrings

## Step 4: Verification

- [ ] Run `make docs` to rebuild API docs
- [ ] Check all code examples execute without errors
- [ ] Verify version numbers match across files
- [ ] Run link checker: `make check-links`
```

---

## Your Task

1. **Audit** this repository's documentation structure
2. **Identify** what types of docs exist and how they're organized
3. **Generate** a customized `/doc-sync` command that:
   - Knows where docs live in THIS repo
   - Maps code changes to relevant documentation
   - Provides actionable checklists
   - Includes verification steps

## Constraints

- The generated command should be **specific** to this repository
- Include actual file paths discovered during audit
- Reference real documentation patterns found
- Don't include sections for documentation that doesn't exist
- Make the command actionable and practical

## Input Variables

If provided, incorporate this context:

```
{{repo_context}}
```

---

**Begin by auditing the repository's documentation structure, then generate the customized /doc-sync command.**

