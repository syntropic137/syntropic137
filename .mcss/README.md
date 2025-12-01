# Minimal Cognitive Switching System (MCSS)

A unified manual system to eliminate the 30–45 min context-switch cost.

⸻

1. Overview

The MCSS is a lightweight framework that helps you re-enter any project within 30 seconds, even after long gaps.

It uses three documents and two rituals:
	•	Mission Control (MC.md)
	•	Session Log (DIARY.md)
	•	Current Active State Artifact (CASA.md)
	•	Session Start Ritual (2–3 min)
	•	Session End Ritual (3–5 min)

The system externalizes your “state graph,” reducing cognitive load and eliminating orientation overhead.

⸻

2. Core Principle

Your next action must always be shovel-ready.
Meaning: it must be so small and concrete that you can begin immediately without thinking, planning, or reloading mental context.

Examples:
❌ “Continue architecture for inference batching”
✔️ “Open batch_orchestrator.py and implement enqueue_job() signature”

❌ “Investigate latency issue”
✔️ “Add timing log to LLM call in client.py and rerun test”

⸻

3. Document 1: Mission Control (MC.md)

# MISSION CONTROL — <Project Name>

## Purpose
(What this project is and why it matters)

## Current Milestone
(What you are working toward right now)

## Architecture / Structure Summary
(Short overview of system design — 5–10 lines)

## Key Decisions
(Bullet list of major decisions you've made)

## Constraints
(Technical, time, budget, dependencies)

## Important Links / Files
- Codebase:
- Repos:
- Specs:
- Diagrams:

## Status Summary
(A quick overview of where the project currently stands)

This file almost never resets.
It is your always-on north star.

⸻

4. Document 2: Session Log (DIARY.md)

# SESSION LOG — <Project Name>

---

## YYYY-MM-DD — Session Start

### Objective
(What I want to accomplish today)

### Where I Left Off
(Copy/paste from last CASA)

### Next Actions (Shovel-Ready Only)
1. ...
2. ...
3. ...

### Notes / Insights
(Any discoveries, reflections, reasoning)

### Obstacles / Open Questions
(Anything unclear, ambiguous, or blocking)

This becomes a chronological record of your thinking, decisions, and progress.

⸻

5. Document 3: Current Active State Artifact (CASA.md)

# CURRENT ACTIVE STATE ARTIFACT (CASA)
Project: <Project Name>

## Where I Left Off
(A compressed summary of your last session)

## What I Was About To Do
(Your "cursor point" — the exact next action)

## Why This Matters
(1–2 sentences of rationale so you never re-think it)

## Open Loops
(Questions, decisions, ambiguities still pending)

## Dependencies
(What you're waiting for — external or internal)

This is your state graph snapshot.
It is overwritten every session.

⸻

6. Ritual 1: Session Start (2–3 minutes)
	1.	Open CASA.md
	2.	Read:
	•	Where I Left Off
	•	What I Was About To Do
	3.	Open the file/code/doc for the next action
	4.	(Optional) Verbal or written intention:
“Today I am doing X. First step is Y.”

This rehydrates your entire context in seconds.

⸻

7. Ritual 2: Session End (3–5 minutes)
	1.	Update DIARY.md with your new entry
	2.	Update CASA.md
	3.	Save/commit
	4.	Close the session cleanly
	5.	Leave with zero mental residue (everything is externalized)

This closes cognitive loops and prevents mental fragmentation.

⸻

8. Why the System Works
	•	Reconstructs your state graph externally
	•	Removes ambiguity and resets
	•	Turns projects into “pause → resume” workflows
	•	Eliminates reorientation time
	•	Encodes rationale, direction, and momentum
	•	Creates a bridge for future automation and AI agents

The combination of CASA + the rituals gives you a smooth, flow-ready entry to any project at any time.

⸻

9. Agentic Upgrade Path (When You’re Ready)

The MCSS maps cleanly to automated systems:
	•	auto-generate CASA from code diffs
	•	extract open loops from conversation logs
	•	auto-write your next actions
	•	sync Mission Control with your event store
	•	allow an LLM to rehydrate your context on session start
	•	enable multi-project cognitive switching with near-zero cost

But for now, the manual foundation gives you 80% of the benefit instantly.