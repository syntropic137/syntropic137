---
description: Generate a repo-specific prime command for onboarding agents
argument-hint: [optional: output path, defaults to .claude/commands/prime.md]
model: sonnet
allowed-tools: Read, Write, Glob, Grep, Bash
---

# Create Prime

Analyze this repository and generate a customized prime command that helps agents quickly understand this specific codebase.

## Purpose

Generate a repo-specific `/prime` command that provides targeted context for agents working in this codebase. The generated command should include hardcoded paths, patterns, and structure specific to this repository.

## Variables

OUTPUT_PATH: $ARGUMENTS  # defaults to .claude/commands/prime.md
PROJECT_ROOT: .

## Instructions

- First, deeply understand THIS repository's structure
- Identify the most important files and directories
- Document the specific patterns used in this codebase
- Generate a prime command that pre-loads this knowledge

## Workflow

### Phase 1: Discover Repository

```bash
# Get project overview
echo "=== Project Structure ==="
git ls-files | head -100

# Find configuration files
echo ""
echo "=== Config Files ==="
ls -la *.toml *.json *.yaml *.yml 2>/dev/null

# Count files by type
echo ""
echo "=== File Types ==="
git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -15
```

### Phase 2: Identify Key Files

Read and note the most important files:

1. **README.md** - Project overview
2. **AGENTS.md** or **CLAUDE.md** - Existing agent instructions
3. **Package config** - `pyproject.toml`, `package.json`, `Cargo.toml`
4. **Architecture docs** - Any docs in `docs/`

### Phase 3: Map Directory Structure

```bash
echo "=== Directory Purpose Map ==="
for dir in */; do
  echo "- $dir"
  ls "$dir" 2>/dev/null | head -5
done
```

### Phase 4: Identify Patterns

Discover:
- **Entry points** - Where does code start?
- **Test locations** - Where are tests?
- **Config patterns** - How is configuration managed?
- **Naming conventions** - What style is used?
- **Build/run commands** - How to build and run?

### Phase 5: Generate Prime Command

Create a customized prime command that includes:

1. **Codebase Structure** section with actual directories
2. **Key Files** section with specific important files
3. **Patterns** section with this repo's conventions
4. **Entry Points** section with actual entry points

## Specified Format

Generate a file with this structure:

```markdown
---
description: Prime context for [PROJECT_NAME]
argument-hint: [optional: focus area]
model: sonnet
allowed-tools: Read, Glob, Grep
---

# Prime

Quickly understand the [PROJECT_NAME] codebase structure and patterns.

## Purpose

Build working context for this codebase by reading key files and understanding the architecture.

## Variables

FOCUS_AREA: $ARGUMENTS

## Codebase Structure

```
[actual directory tree with purposes]
```

## Key Files

| File | Purpose | Read Priority |
|------|---------|---------------|
| [actual path] | [what it does] | 1 (high) |
| [actual path] | [what it does] | 2 (medium) |

## Patterns

- **Language:** [actual language/framework]
- **Testing:** [actual test pattern]
- **Config:** [actual config approach]
- **Naming:** [actual conventions]
- **Build:** [actual build command]

## Workflow

1. **Read Foundation**
   - Read [specific key files for this repo]
   
2. **Understand Architecture**
   - Review [specific architecture files]
   
3. **If FOCUS_AREA provided**
   - Deep dive into that directory
   - Read its README if exists

## Report

## [PROJECT_NAME] Context

**Purpose:** [one-line description]
**Stack:** [language/framework]

### Structure Understanding
[bullet points of key directories]

### Ready to Work On
Based on this context, I can now help with:
- [capability based on codebase]
- [capability based on codebase]
```

## Report

## Prime Command Generated

**Output:** {OUTPUT_PATH}

**Customizations:**
- [x] Directory structure mapped
- [x] Key files identified
- [x] Patterns documented
- [x] Entry points listed

**Next:** Install the prime command:
```bash
cp {OUTPUT_PATH} .claude/commands/prime.md
```

## Examples

### Example 1: Generate for current repo
```
/create-prime
```

### Example 2: Output to specific location
```
/create-prime ./commands/prime.md
```

### Example 3: Generate for Claude Code
```
/create-prime .claude/commands/prime.md
```

