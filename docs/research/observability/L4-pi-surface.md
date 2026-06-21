# Obs L4 — "PI" harness observability surface (research + scoping)

**Date:** 2026-06-20
**Author:** research pass (read-only)
**Question:** What is the "PI" coding-agent harness in this operator's stack? Is
it installed on this box? If identifiable, map its observability surface like the
other lanes. If not, state exactly what operator input is needed. Also note the
general pattern any future harness exporter adapter must satisfy.

---

## TL;DR

- **PI is NOT identifiable from this box.** It exists in the stack as a single
  *placeholder line* in the orchestration model card — "(PI / others) – to be
  added" — under "Future harnesses (not yet wired)." Nothing else anywhere
  references it: no binary, no ntm flag, no config, no adapter, no docs.
- **PI is NOT installed** (`which pi` / `which PI` → not found; nothing under
  `~/.local/bin`, `~/.config`, agentic-primitives, or syntropic137).
- Therefore its observability surface **cannot be mapped** — we don't know what
  PI is (acronym unexpanded), where to get it, or what its CLI looks like. See
  **OPERATOR INPUT NEEDED** below.
- The *next* real harness is **opencode** (`--oc` flag already in ntm; docs +
  issue #51 exist; "planned next" per public docs). Its observability surface IS
  designed and documented — use it as the worked example of the general pattern.

---

## Evidence (what was checked)

### The model card (canonical harness/model source of truth)

Path on this box (the AGENTS.md-referenced path under the worktree does NOT
exist; the real file is in the orchestration skill home):

- `/home/ubuntu/orchestration/.agents/skills/flywheel-orchestration/references/agent-models.md`
- (mirrors also exist under `~/Code/NeuralEmpowerment/agentic-coding-flywheel/lib/orchestration-home/...`)

It declares exactly three wired harnesses — **Claude (`--cc`)**, **Codex
(`--cod`)**, **Gemini (`--gmi`)** — and a "Future harnesses (not yet wired)"
section containing the only two mentions of anything else:

> - **opencode** (`--oc`) — present in ntm's flag set; not yet part of the routing policy.
> - **(PI / others)** — to be added.

That second bullet is the *entire* footprint of "PI" in the stack. The acronym is
never expanded and there is no link, vendor, or CLI name.

### Installation check — negative

- `which pi`, `which PI` → not found.
- `~/.local/bin` → no `pi`/`opencode`/`crush`/`aider`/`amp` binary (only the
  unrelated `pip-audit` symlink, a false-positive substring match).
- `which opencode` → not found either (opencode is documented/planned but also
  not installed yet).

### Stack-wide search — negative for PI, positive for opencode

- `grep -rinE '\bPI\b'` across the orchestration skill → only the one model-card
  placeholder line.
- agentic-primitives: no harness class / adapter / provider named PI (all `pi`
  hits are substrings: pipe, pip, api, etc.).
- syntropic137 worktree: zero PI references. Many **opencode** references,
  including a full design doc (see next section).

### ntm spawn flags (live `ntm spawn --help`)

```
--cc  N[:model[:effort]]   Claude agents
--cod N[:model[:effort]]   Codex agents
--gmi N[:model[:effort]]   Gemini agents
--oc  N[:model[:effort]]   Opencode agents
```

There is **no `--pi` flag** (nor any PI-shaped flag). opencode has a flag but the
model card says it is "not yet part of the routing policy."

---

## How the existing lanes are observed (baseline to match)

So a future harness lane has a concrete target to conform to:

- **Claude lane (today's only live capability):** Claude CLI runs *inside* a
  Docker workspace and emits **JSONL on stdout**. That stream is captured
  externally and parsed by the adapters layer:
  - `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py`
    (`AgenticEventStreamAdapter` — streams stdout, tracks exit code)
  - `packages/syn-adapters/src/syn_adapters/events/parse.py`, `buffer.py`,
    `buffer_flush.py` — JSONL → domain events, buffered/flushed.
  - `packages/syn-adapters/src/syn_adapters/collector/client*.py` — batched HTTP
    client to the collector.
- **Collector ingestion (`packages/syn-collector/`):** accepts events over HTTP
  (`POST /events`) and **OTLP** (there are OTLP routes/parser tests:
  `tests/test_otlp_routes.py`, `test_otlp_parser.py`), with a store, dedup, and a
  file watcher (`watcher_runner.py`).
- **Domain side:** `WorkflowExecutionEngine` is the single owner of event
  recording, keyed by `session_id`; telemetry rides **Lane 2 (observability)**,
  never through aggregates (see AGENTS.md two-lane rules).

Net: an exporter for a new harness must produce the same domain telemetry events,
keyed by `session_id`, and deliver them to the collector (HTTP `/events` or OTLP).

---

## General pattern: minimum surface a future-harness exporter adapter needs

This is the reusable answer that applies to PI, opencode, or any future harness.
opencode is the worked reference (`docs/features/opencode-plugin-observability.md`,
issue #51). For ANY harness, the exporter needs a **source** of these signals and
a **sink** into the Syn137 collector:

**1. A telemetry source — at least one of (in order of preference):**
   - **Structured stream** the host can capture (Claude model = JSONL on stdout).
     Cheapest to integrate; no in-process code.
   - **Plugin / hook API** the harness fires in-process (opencode model =
     `tool.execute.before/after`, `session.created/idle/error`, `file.edited`,
     `message.updated`, …). Needed when there's no rich stdout stream.
   - **OTLP / native telemetry** the harness already emits → point it at the
     collector's OTLP route.

**2. A session identity:** a stable `session_id` per agent run (plus
   provider/model/backend tags). Everything is keyed on `session_id`.

**3. An event mapping** from harness-native events → Syn137 domain events. The
   minimum viable set (matching what the Claude lane and the opencode design both
   cover):
   - session lifecycle → `AgentSessionStarted` / `…Completed` / `…Failed`
   - tool lifecycle → `ToolExecutionStarted` / `…Completed` (name, args,
     duration, tokens)
   - token/cost usage (per turn and totals)
   - file operations / message events (nice-to-have, not blocking)

**4. A transport/sink:** batched, retrying HTTP to the collector
   (`SYN_COLLECTOR_URL`, `POST /events`) or OTLP. Tag events `backend: "<harness>"`.

**5. Lane discipline:** telemetry goes to the observability recorder/collector
   only — never through domain aggregates (Lane 2, append-only, replay-exempt).

If a harness provides **none** of (structured stream / plugin hooks / OTLP), it
cannot be observed without upstream changes — that gap is the first thing to
determine for any new harness, including PI.

---

## OPERATOR INPUT NEEDED (for PI specifically)

PI cannot be scoped further from this box. To proceed we need from the operator:

1. **What is "PI"?** Expand the acronym / name the product. (It's only a
   placeholder string in the model card today — no vendor, repo, or URL.)
2. **Where do we get it?** Install source (npm/cargo/brew/curl), repo URL, and
   whether it's a Max/subscription/API-billed harness (affects quota routing in
   the model card).
3. **What is its CLI?** Binary name + invocation, and the `ntm` flag it should
   get (Claude/Codex/Gemini use `--cc`/`--cod`/`--gmi`; opencode reserved `--oc`).
4. **What is its observability surface?** Specifically which of the three source
   types it offers:
   - structured stdout stream (like Claude JSONL)? format?
   - plugin/hook API (like opencode)? event names?
   - native OTLP / telemetry export?
   - none (→ upstream work required)?
5. **Session identity:** how it exposes/accepts a `session_id` and emits
   model/provider/token/cost data.

Once 1–4 are answered, mapping PI's surface is a fill-in of the "general pattern"
table above, modeled on the opencode doc.

---

## Pointers

- Model card (harness source of truth): `~/orchestration/.agents/skills/flywheel-orchestration/references/agent-models.md`
- opencode observability design (worked example of the pattern):
  `docs/features/opencode-plugin-observability.md` (issue #51)
- Claude lane capture: `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py`, `.../events/parse.py`
- Collector sink: `packages/syn-collector/` (`POST /events`, OTLP routes)
- ntm flags: `ntm spawn --help` (`--cc/--cod/--gmi/--oc`; no `--pi`)
