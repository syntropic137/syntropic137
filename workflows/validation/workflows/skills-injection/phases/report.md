---
model: haiku
description: "Report which skills actually reached the agent's context"
argument-hint: "[ignored]"
allowed-tools: Read,Write,Glob,Grep
timeout-seconds: 300
---

Write `artifacts/output/report.md` containing exactly three lines, each
starting at column 1, and nothing else. The file is what the platform reads
to decide whether this run passed; an answer only spoken back counts as no
answer at all.

1. `SENTINEL: <value>` — the deployment sentinel from the `deployment-sentinel`
   skill. If that skill is not in your context, write `SENTINEL: MISSING`.
   Do not guess a plausible value.

2. `EXTERNAL_SKILL: <present|MISSING>` — whether a skill named
   `doc-coauthoring` (fetched from an external repository, not vendored in this
   package) is available to you.

3. `SKILL_SOURCE: <how you obtained the sentinel>` — say `context` if the skill
   was already available to you, or `searched` if you had to look for it on
   disk. This distinction matters: a skill the agent must hunt for has already
   lost the mechanism, even when the answer turns out right.

Answer only from what is actually in your context. A wrong `MISSING` is a useful
result; a fabricated sentinel is worse than a failure, because it makes a broken
deployment look healthy.
