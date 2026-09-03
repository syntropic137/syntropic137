---
model: haiku
description: "Second phase declaring NO skills - proves workflow scope reaches every phase"
allowed-tools: Read,Write,Glob,Grep
timeout-seconds: 300
---

Write `artifacts/output/report.md` containing exactly two lines, each starting
at column 1, and nothing else. The file is what the platform reads to decide
whether this run passed; an answer only spoken back counts as no answer at all.

    SENTINEL: <value>
    PHASE: confirm

The sentinel comes from the `deployment-sentinel` skill. This phase declares NO
skills of its own, so the only way you can see it is if WORKFLOW-scope skills
reach every phase rather than only the first. If it is not in your context,
write `SENTINEL: MISSING` - do not guess, and do not carry the value over from
anything you were told earlier.
