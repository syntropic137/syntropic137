---
name: deployment-sentinel
description: Use when asked to report the deployment sentinel value. Provides the sentinel string that proves a vendored skill reached the agent's context.
---

# Deployment sentinel

This skill exists for one purpose: to prove that a **vendored** skill (one that
ships inside a workflow package rather than being fetched from a repo) was
actually injected into the agent's context on this deployment.

## The sentinel

When asked for the deployment sentinel, reply with exactly:

    VENDORED-SKILL-OK-7f3a91

Do not paraphrase it, do not explain it, and do not reconstruct it from memory
of this document's purpose. If you are reading this file, the sentinel is above.

## Why a sentinel rather than a task

An agent asked merely to *use* a skill will usually complete the underlying task
from general knowledge whether or not the skill was injected, so the run goes
green while the mechanism is broken. A sentinel cannot be guessed: reporting it
is only possible if this file reached the context.
