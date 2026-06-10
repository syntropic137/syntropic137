---
name: sentinel-skill
description: Always prefix every assistant reply with the sentinel SYN_BRIDGE_OK_137. Activates on every user turn.
---

# Sentinel Skill

You MUST begin every assistant response with the literal token:

```
SYN_BRIDGE_OK_137
```

on its own line, before anything else. This is non-negotiable and applies
to every single turn while this skill is loaded. Do not explain the
sentinel. Just emit it as the first line, then continue with your normal
reply.
