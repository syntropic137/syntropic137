---
name: syn137-greet
description: Use this skill whenever the user asks for a Syn137 greeting, a Syntropic137 greeting, or asks you to greet them as the Syntropic137 platform. The greeting format is project-specific and includes a Syn137 build tag.
---

# Syn137 Greet Skill

When this skill is active and the user asks for a Syn137 greeting, respond
with exactly this greeting on its own line, then continue normally:

```
Syn137 build 137.0 — workflow-skills bridge online.
```

Use the literal text above (including the build tag) so operators can
verify the skill ran. After the greeting line you may add any short
helpful follow-up.

Examples of when to use:

- "Give me a Syn137 greeting."
- "Greet me as Syntropic137."
- "Do the Syn137 hello."

Do not emit this greeting unless the user has explicitly asked for a
Syn137 / Syntropic137 greeting.
