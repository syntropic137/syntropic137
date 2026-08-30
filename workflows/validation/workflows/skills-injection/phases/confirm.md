---
model: haiku
description: "Second phase declaring NO skills - proves workflow scope reaches every phase"
allowed-tools: Read,Glob,Grep
timeout-seconds: 300
---

Report exactly two lines and nothing else.

    SENTINEL: <value>
    PHASE: confirm

The sentinel comes from the `deployment-sentinel` skill. This phase declares NO
skills of its own, so the only way you can see it is if WORKFLOW-scope skills
reach every phase rather than only the first. If it is not in your context,
write `SENTINEL: MISSING` - do not guess, and do not carry the value over from
anything you were told earlier.
