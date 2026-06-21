# The Agent Workspace Standard (vision spec)

Status: VISION CAPTURE (operator, 2026-06-22). Not an implementation plan; a
durable record of the target so it is not lost. Needs more experimentation.
Ultimate home: the Agent Paradise standard system (APSS) / agentic-primitives.
This copy lives in syntropic137 because that is where the proving work is
happening; PROMOTE it to APSS/agentic-primitives when it firms up.

## 1. Purpose and vision

Capture the boundary between "an app/orchestrator" and "a place where agents
run" as a single, deployment-agnostic INTERFACE, and encode that interface as
a standard in APSS. The contract is the product. Once the boundary is a
standard, the SAME workspace contract can be backed by any location:

- Docker container (what Syntropic137 uses today)
- Docker's new VM feature
- macOS VM
- E2B
- a VPS
- a local MacBook

and ANY app or orchestration system can plug into a workspace anywhere, without
caring how it is implemented. Syntropic137 becomes a CONSUMER of the standard;
its Docker-workspace implementation is fully abstracted and swappable later.

The boundary is the leverage: it decouples workspace LOCATION from workspace
CAPABILITY, so focused agents compose and deploy anywhere with their context
intact.

## 2. The workspace contract (the interface)

Every conforming workspace exposes these capabilities regardless of where it
runs:

1. RUN AGENTS - any harness (claude / codex / gemini / pi / opencode),
   interactive or headless, with per-harness autonomy handled inside.
2. INJECT CONTEXT AT STARTUP - plugins + skills + tools + LSP + focus, injected
   per-harness in a harness-agnostic way (the context:{} standard). This is what
   lets agents be FOCUSED + contained rather than overloaded.
3. EXPORT OBSERVABILITY - git hooks + all hooks + telemetry, standardized across
   every harness (the HarnessExporter standard). PROVEN cross-harness already
   (Claude + Codex land canonical rows in agent_events).
4. EXPORT SESSION LOGS - every agent session captured and shipped to a session
   manager / database, regardless of deployment, so the operator always keeps
   their valuable session data.
5. MEMORY - a memory layer (Hindsight) the workspace can read and write.
6. EXTENSIBILITY - new capabilities/plugins plug into the standard via a clean,
   easy-to-extend model. This is the part that needs deep design (see Sec 6).

## 3. The two killer capabilities (operator's current top priority)

Across ALL harnesses, in one unified workspace standard:

- PLUGIN + SKILL INJECTION for every harness (claude/codex/gemini/pi/opencode) -
  "cloud plugins" generalized so a workspace boots an agent with exactly the
  context/skills/plugins it needs and nothing more.
- OBSERVABILITY EXPORT for every harness - git hooks and all hooks standardized,
  so telemetry/cost/session events flow uniformly no matter the harness.

Doing this in a STANDARDIZED, GENERIC way is the whole point: support many
harnesses without bespoke per-harness work each time.

## 4. The payoff: focused, contained agents

Structure each agent as a contained environment with specific plugins/skills, so
it is focused and not overloaded. Agents delegate to each other; each gets its
context + skills + plugins injected at startup. The workspace standard lets these
agents scale across many applications and orchestration systems: you can stand up
an agent for any harness, and it has the right context, on any deployment target.

### Example agent: the Architecture Agent (a phase-3 illustration)

- Hyper-specialized for ONE application's build. A generalist architect that
  keeps that application's VISION in mind (the "generic parts architect").
- Relies on APSS: it knows there is a Purpose-and-Vision document somewhere in
  the repo and uses it to guide itself.
- Core principle it enforces: maintain LAYER SEPARATIONS and responsibilities.
  It continuously reviews code updates and pools functionality to the layers
  that need it, keeping layers decoupled.
- Needs: the plugin + the workspace + code-review capability.
- This is one of a CLASS of agents the standard should make cheap to build.

## 5. Capabilities to spin off from the workspace (planks + status)

- Plank 1 RUN AGENTS - EXISTS (interactive-tmux provider; claude/codex/gemini).
- Plank 2 CONTEXT INJECTION (plugins/skills/tools/lsp/focus) - Claude-only today;
  harness-agnostic generalization DESIGNED (context:{} block + per-harness
  adapters). NOT yet built.
- Plank 3 OBSERVABILITY EXPORT - PROVEN cross-harness (Claude + Codex via the
  HarnessExporter standard; route-conformance test lands rows in agent_events).
  Gemini / PI / opencode adapters are the same pattern repeated.
- Plank 4 SESSION-LOG EXPORT - a session manager (deploying on the Mac Mini)
  takes all agents' session logs and saves them to a database. So no matter
  where deployed (VPS / cloud / MacBook), the operator keeps their data and can:
  use it as a RAG lookup, mine it, and do continual self-improvement. High value.
- Plank 5 MEMORY - Hindsight, the memory layer (on the Mac Mini). The standard
  must let memory plug in as a first-class capability.
- Plank 6 EXTENSIBILITY MODEL - how all of the above (session manager, memory,
  observability, injection) attach to the standard and how NEW plugins are added
  easily. Needs deep design.

## 6. Open questions / where experimentation is needed

- THE EXTENSIBILITY MODEL is the crux: how do session-manager, memory,
  observability, and injection plug into the workspace standard cleanly, and how
  is a new plugin added with minimal effort? Design this deliberately.
- How is the contract ENCODED in APSS? (a schema for the interface, fitness
  functions that verify a given workspace implementation conforms, a capability
  manifest per deployment target.)
- Session manager + Hindsight as standard plugins: the integration shape.
- The deployment-target adapters (Docker / Docker-VM / macOS-VM / E2B / VPS /
  local): what is the minimal driver each must implement to satisfy the contract.
- Phase-3: how agent standards (e.g. the Architecture Agent class) THEMSELVES
  rely on APSS - reading a repo's Purpose-and-Vision and self-guiding.

## 7. Phasing

- Phase 1 (now): observability standard proven cross-harness (Claude + Codex).
- Phase 2: generalize context injection across harnesses; add Gemini/PI/opencode
  observability adapters; bring session-log export + memory in as standard
  plugins; define the extensibility model.
- Phase 3: agent standards on APSS - composable, focused, vision-aware agents
  (the Architecture Agent class) deployable across orchestration systems and
  workspace locations.

## 8. Evidence so far (what is already proven/designed)

- Observability: HarnessExporter standard; Claude + Codex land canonical rows in
  agent_events (docs/research/observability/L5-design-v2.md + the inc0/inc1
  branches feat/harness-exporter-inc0, feat/harness-exporter-inc1-codex).
- Injection: research mapping the Claude-only injection surface + the context:{}
  generalization (docs/research/observability/ + the injection findings).
- Workspace: the interactive-tmux provider + scalability profiling
  (exec-poll-bound, not RAM-bound).

## 9. Why this matters (operator)

Supports multiple workspaces; abstracts implementation behind a standard (the
APSS value: it defines boundaries); guarantees session capture + observability +
plugin injection across harnesses; enables focused contained agents that
delegate to each other; and does it generically so many harnesses are supported
without per-harness unique updates. Syntropic137 (and any future app) just relies
on the standard.
