---
description: Zero-friction Syntropic137 onboarding — from git clone to running stack
argument-hint: [dev|selfhost]
model: sonnet
allowed-tools: Bash, Read, Glob, Grep, AskUserQuestion
---

# Onboard

Set up Syntropic137 from scratch — detect current state, fix what's missing, get the stack running.

## Variables

MODE: $ARGUMENTS

## Instructions

### Step 1: Read Skill Context

Read `.claude/skills/onboarding/SKILL.md` for full context on prerequisites, detection checks, setup paths, and common fixes.

### Step 2: Detect Current State

Run the environment detection checklist from the skill. Check each item and build a status report:

- [ ] Docker running (`docker info`)
- [ ] Git submodules initialized (`lib/agentic-primitives/.git` and `lib/event-sourcing-platform/.git` exist)
- [ ] `.env` exists and has values (not just template)
- [ ] `infra/.env` exists (selfhost only)
- [ ] Required tools installed (uv, just, pnpm, node)
- [ ] Python dependencies installed (`.venv/` exists)
- [ ] Dashboard deps installed (`apps/syn-dashboard-ui/node_modules/` exists)
- [ ] Workspace image built (`docker images agentic-workspace-claude-cli`)
- [ ] Services already running (`docker ps`)

Report what's done and what's missing before proceeding.

### Step 3: Choose Mode

If MODE is `dev` or `selfhost`, use that. Otherwise, ask the user:

Use AskUserQuestion with these options:
- **Dev** — Local development (`just onboard-dev`). Best for contributing code. Optionally add GitHub App and Cloudflare tunnel.
- **Selfhost** — Production deployment (`just onboard` wizard). Best for running your own instance.

### Step 4: Execute

**Dev path:**

1. Ask the user if they also want GitHub App and/or Cloudflare tunnel setup:
   - Use AskUserQuestion with multiSelect options: **GitHub App** (`--github`), **Cloudflare Tunnel** (`--tunnel`), **Neither (just dev stack)**
2. Build the flags string from their selections
3. Run `just onboard-dev` (with optional `--github` and/or `--tunnel` flags)
4. The recipe is idempotent — it skips steps already completed

**Selfhost path:**

1. Run `just onboard` (the interactive setup wizard handles everything)
2. After wizard completes: `just selfhost-up`
3. Optionally: `just selfhost-seed`

For **dangerous or irreversible actions** (like overwriting `.env`, resetting volumes), always ask the user first via AskUserQuestion.

### Step 5: Report

After setup completes, provide a summary:

1. **What was done** — list each step executed (and skipped)
2. **Access URLs:**
   - Dashboard UI: http://localhost:5173
   - Dashboard API: http://localhost:8000/docs
   - API Health: http://localhost:8000/health
3. **Next commands:**
   - `just dev-logs` — tail service logs
   - `just dev-stop` — stop services
   - `just health-check` — verify services
   - `just qa` — run full QA suite
4. **Any warnings** — missing optional config (API keys, 1Password, etc.)
