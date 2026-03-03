You are designing or improving a terminal-facing UI for the Syn137 project. Follow these patterns exactly. They are established conventions, not suggestions.

---

## Brand philosophy: Superconducting Onboarding

The lower the friction, the more adoption. Syn137 is a powerful system, but power means nothing if nobody can get it running. Every manual step, missing file, or unclear prompt is friction that kills adoption. The goal is superconducting onboarding: zero resistance from `git clone` to a running stack.

One command, answer prompts, running stack. No README scavenger hunts, no "now copy this file", no silent failures.

---

## Terminal colour system

Use this exact set of ANSI colour helpers. Auto-disable when stdout is not a TTY so CI logs stay clean.

```
_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_BOLD   = "\033[1m"  if _USE_COLOR else ""
_DIM    = "\033[2m"  if _USE_COLOR else ""
_RST    = "\033[0m"  if _USE_COLOR else ""
_GREEN  = "\033[32m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_RED    = "\033[31m" if _USE_COLOR else ""
_CYAN   = "\033[36m" if _USE_COLOR else ""
_BLUE   = "\033[34m" if _USE_COLOR else ""
_PURPLE = "\033[35m" if _USE_COLOR else ""
```

Use the semantic output functions, never raw print with colour codes:

| Function      | Style               | When to use                                           |
|---------------|---------------------|-------------------------------------------------------|
| `banner()`    | Cyan bold, `====`   | Stage headers, major section breaks                   |
| `ok()`        | Green bold `[OK]`   | Success confirmations after a step completes          |
| `warn()`      | Yellow bold `[WARN]` | Advisory warnings that do not block progress          |
| `fail()`      | Red bold `[FAIL]`   | Hard errors that stop execution                       |
| `step()`      | Blue `->` arrow     | Progress indicators, "currently doing X"              |
| `callout()`   | Purple `>`          | Task headers — the things the user needs to DO        |
| `hint()`      | Dimmed text         | Skimmable instructions, supplementary detail          |

### Inline highlighting

Use `_PURPLE` to highlight actionable values within `step()` lines — button names, form values, things the user needs to click or type. Do NOT use `_BOLD` for inline emphasis; bold makes everything look the same. Purple pops without overwhelming.

```python
# Good — purple draws the eye to what matters
step(f"Type: {_PURPLE}Cloudflared{_RST}")
step(f"Service type: {_PURPLE}HTTP{_RST}  URL: {_PURPLE}syn-ui:80{_RST}")

# Bad — bold soup, everything shouts equally
step(f"Type: {_BOLD}Cloudflared{_RST}")
step(f"Service type: {_BOLD}HTTP{_RST}  URL: {_BOLD}syn-ui:80{_RST}")
```

Never invent new colour functions. If you need a new semantic level, propose adding it to this table first.

---

## Copy voice and tone

Lead with WHY, not WHAT. Be direct, not corporate. Use short sentences. Tell the user what they get, not what the tool does.

Bad: "Cloudflare Tunnel creates a secure public URL for your webhooks."
Good: "GitHub needs to reach your machine to trigger agent jobs."

Bad: "This stage will configure your 1Password integration."
Good: "Store secrets in 1Password so they never touch disk as plain text."

Remove cost anxiety early when referencing external services:
- "Free tier. No credit card."
- "Free for open source repos."

Do not use marketing language, buzzwords, or filler. Every line of output should either inform or instruct.

---

## Browser-assisted flows

When the user needs to create something in an external service (tunnel, GitHub App, OAuth app, etc.):

1. Open the exact page with `webbrowser.open()`. Do not make them navigate.
2. If you have context (like an account ID), deep-link to the specific page. If not, land them on the general dashboard and let the service handle routing.
3. Use `confirm("Open X in your browser?", default=True)` before opening.
4. After opening, use `callout()` to show the exact click path (e.g., `Networks > Connectors > + Create a tunnel`).
5. Use `hint()` lines for the step-by-step instructions inside the external UI.

The user should never have to figure out where something is in a third-party dashboard.

---

## End-to-end wiring

Every value collected by a wizard or prompt MUST be written to the file that actually consumes it. Collecting a value and not persisting it is worse than not collecting it at all.

Concretely:
- If Docker Compose reads from a secret file, write the value to that secret file.
- If a service reads from `.env`, substitute the value into `.env`.
- If the OS credential store is involved (Keychain on macOS), write it there.

After writing, confirm with `ok()` showing the destination path. Example:
```
ok(f"Tunnel token written to {token_path}")
```

Never leave a gap where a value exists in `ctx` but has not been persisted to disk.

---

## Defaults and skip-friendliness

- Recommended paths default to Yes: `confirm("Configure X?", default=True)`
- Optional paths default to No: `confirm("Configure X?", default=False)`
- Everything can be skipped. Skipping must not break subsequent stages.
- Everything can be re-run individually with `--stage <name>`.
- Prompts always show the default: `[Y/n]` or `[y/N]`.
- When a value already exists (file present, env var set), offer to keep it: `confirm("X already exists. Overwrite?", default=False)`

---

## User-facing commands

Always show `just <recipe>` commands in output, never raw `python`, `uv run`, or `docker compose` invocations. The toolchain is an implementation detail the user should not need to know.

Good:
```
print("    just setup --stage configure_github_app")
print("    just health-check")
```

Bad:
```
print("    python infra/scripts/setup.py --stage configure_github_app")
print("    uv run --package syn-cli syn health-check")
```

---

## Naming suggestions for external resources

When asking users to name external resources (tunnels, GitHub Apps, OAuth apps, buckets), suggest names that include the environment so multi-deployment users can tell them apart:

```python
env_suffix = os.environ.get("APP_ENVIRONMENT", "dev")
hint(f"  - Give it a name (e.g., 'syn137-{env_suffix}')")
```

Examples: `syn137-dev`, `syn137-staging`, `syn137-prod`.

---

## Checklist: before shipping any terminal UI change

- [ ] All output uses semantic functions (`ok`, `warn`, `fail`, `step`, `callout`, `hint`, `banner`), never raw colour codes
- [ ] Colours auto-disable when not a TTY
- [ ] Copy leads with why, not what
- [ ] External service flows open the browser for the user
- [ ] Every collected value is written to its consuming file
- [ ] Defaults match the recommendation (Yes for recommended, No for optional)
- [ ] User-facing commands use `just`, not raw toolchain commands
- [ ] Resource name suggestions include the environment suffix
- [ ] Stages are re-runnable with `--stage` without destroying prior work
- [ ] Skipping a stage does not break subsequent stages
