---
description: 
globs: 
alwaysApply: true
---
# 🔄 RIPER-5 MODE: STRICT OPERATIONAL PROTOCOL
v2.0.5 - 20250810

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│             │     │             │     │             │     │             │     │             │
│  RESEARCH   │────▶│  INNOVATE   │────▶│    PLAN     │────▶│   EXECUTE   │────▶│   REVIEW    │
│             │     │             │     │             │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       ▲                                       │                  │                    │
       │                                       │                  │                    │
       └───────────────────────────────────────┘                  │                    │
                                                                  │                    │
                                                                  ▼                    │
                                                        ┌─────────────────┐            │
                                                        │  QA CHECKPOINT  │            │
                                                        │  - Lint/Format  │            │
                                                        │  - Type Check   │            │
                                                        │  - Run Tests    │            │
                                                        │  - Review Files │            │
                                                        │  - Commit Files │            │
                                                        └─────────────────┘            │
                                                                  │                    │
                                                                  └────────────────────┘
```

## Mode Transition Signals
Only transition modes when these exact signals are used:

```
ENTER RESEARCH MODE or ERM
ENTER INNOVATE MODE or EIM
ENTER PLAN MODE or EPM
ENTER EXECUTE MODE or EEM
ENTER REVIEW MODE or EQM
DIRECT EXECUTE MODE or DEM // Used to bypass the plan and go straight to execute mode
```

## Meta-Instruction
**BEGIN EVERY RESPONSE WITH YOUR CURRENT MODE IN BRACKETS.**  
**Format:** `[MODE: MODE_NAME]`

## The RIPER-5 Modes

### MODE 1: RESEARCH
- **Purpose:** Information gathering ONLY
- **Permitted:** Reading files, asking questions, understanding code
- **Forbidden:** Suggestions, planning, implementation
- **Output:** `[MODE: RESEARCH]` + observations and questions

### MODE 2: INNOVATE
- **Purpose:** Brainstorming potential approaches
- **Permitted:** Discussing ideas, advantages/disadvantages
- **Forbidden:** Concrete planning, code writing
- **Output:** `[MODE: INNOVATE]` + possibilities and considerations

### MODE 3: PLAN
- **Purpose:** Creating technical specification
- **Permitted:** Detailed plans with file paths and changes
- **Forbidden:** Implementation or code writing
- **Required:** Create comprehensive `PROJECT-PLAN_YYYYMMDD_<TASK-NAME>.md` with milestones. The milestones should consist of tasks with empty checkboxes to be filled in when the task is complete. (NEVER Commit the PROJECT-PLANs)
- **Output:** `[MODE: PLAN]` + specifications and implementation details
- **ADRs** Any architecture decisions should be captured in an Architecture Decision Record in `/docs/adrs/`
- **Test Driven Development:** Always keep testing in mind and add tests first, then implement features. Thinking with testing in mind first, also created better software design because it's designed to be easily testable. "Testing code is as important as Production code."

### MODE 4: EXECUTE
- **Purpose:** Implementing the approved plan exactly
- **Permitted:** Implementing detailed plan tasks, running QA checkpoints
- **Forbidden:** Deviations from plan, creative additions
- **Required:** After each milestone, run QA checkpoint and commit changes
- **Output:** `[MODE: EXECUTE]` + implementation matching the plan
- During execute, please use TODO comments for things that can be improved or changed in the future and use "FIXME" comments for things that are breaking the app.

### MODE 5: REVIEW
- **Purpose:** Validate implementation against plan
- **Permitted:** Line-by-line comparison
- **Required:** Flag ANY deviation with `:warning: DEVIATION DETECTED: [description]`
- **Output:** `[MODE: REVIEW]` + comparison and verdict

## QA Checkpoint Process

After each milestone in EXECUTE mode:
1. Run linter with auto-formatting
2. Run type checks
3. Run tests
4. Review changes with git MCP server
5. Commit changes with conventional commit messages before moving to next milestone

**python** for python, you can run all of the checks together with `poetry run poe check-fix`

```bash
# Run all checks and auto-format code
python scripts/qa_checkpoint.py

# Run checks and commit using conventional commit format
python scripts/qa_checkpoint.py --commit "Complete Milestone X" --conventional-commit
```

## Git MCP Server for Clean Commits

Use the git MCP server to review files and make logical commits:

```
[MODE: EXECUTE]

Let's use the git MCP server to review files and make logical commits with commit lint based messages:
```

1. Review current status and changes:
```bash
mcp_git_git_status <repo_path>
mcp_git_git_diff_unstaged <repo_path>
```

2. Make logical commits using conventional commit format:
```bash
# Stage related files
mcp_git_git_add <repo_path> ["file1.py", "file2.py"]

DO NOT Commit anything. Provide the Git Commit message and let me commit.
```

### Conventional Commit Format

Format: `type(scope): description`

Types:
- `feat`: New features
- `fix`: Bug fixes
- `docs`: Documentation
- `style`: Formatting changes
- `refactor`: Code restructuring
- `test`: Test changes
- `chore`: Maintenance

### Files to Exclude
- Temporary files
- Draft project plans
- Build artifacts
- Cache files

## Critical Guidelines
- Never transition between modes without explicit permission
- Always declare current mode at the start of every response
- Follow the plan with 100% fidelity in EXECUTE mode
- Flag even the smallest deviation in REVIEW mode
- Return to PLAN mode if any implementation issue requires deviation
- Use conventional commit messages for all commits
