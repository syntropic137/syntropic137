---
description: Start development environment (smart prereq detection)
argument-hint: [fresh]
model: sonnet
allowed-tools: Bash, Read, Glob, AskUserQuestion
---

# Start Dev

Quick "get me coding" — check prerequisites and start the Syntropic137 dev stack.

## Variables

ARG: $ARGUMENTS

## Instructions

### Step 1: Read Skill Context

Read `.claude/skills/onboarding/SKILL.md` for prerequisites and detection checks.

### Step 2: Quick Prereq Scan

Run fast checks (don't install anything yet):

1. **Docker running** — `docker info >/dev/null 2>&1`
2. **uv available** — `uv --version`
3. **pnpm available** — `pnpm --version`
4. **`.env` exists** — `test -f .env`
5. **Submodules initialized** — `test -d lib/agentic-primitives/.git`
6. **Python deps installed** — `test -d .venv`

### Step 3: Fix or Suggest

Based on scan results:

- **Docker not running:** Tell the user to start Docker Desktop and retry. Do not proceed without Docker.
- **Missing uv/pnpm:** Provide install commands from the skill. Ask if the user wants you to install them.
- **Missing `.env`:** Create from `.env.example` with dev defaults. Ask about API keys.
- **Submodules missing:** Run `just submodules-init`.
- **Python deps missing:** Run `uv sync`.

If **3+ things are missing**, suggest running `/onboard dev` instead — it's more thorough.

### Step 4: Start

If all prerequisites pass:

- If ARG is `fresh`: run `just dev-fresh` (clean rebuild with volume wipe — confirm with user first)
- Otherwise: run `just dev`

After starting, report:
- Dashboard UI: http://localhost:5173
- Dashboard API: http://localhost:8000/docs
- Run `just dev-logs` to see output
- Run `just dev-stop` when done
