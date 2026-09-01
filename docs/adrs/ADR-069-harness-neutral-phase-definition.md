# ADR-069: Harness-neutral phase definition, and where the translation lives

- **Status**: Accepted (D1-D2, D6 remain Proposed; see Implementation notes)
- **Date**: 2026-09-01
- **Issue**: #1039, #1052, #802, #964, #1009
- **Related**: ADR-068 (remove interactive-tmux path), ADR-066 (separation of concerns), ADR-027 (workspace provider images)

## Context

A workflow phase should declare, in one document, what job it is doing and what
it needs to do that job: a harness, a model, a prompt, the skills that make it
competent, and the tools it may use. Each phase should carry only what that job
needs, so context stays small and the agent stays focused.

Four things stand between that goal and the code as it exists today. All four
were established by measurement or by reading source, not by reasoning from
documentation, and each is cited below.

### 1. The phase schema descends from the slash command, which is dead

`workflow_definition.py:288` heads a block of fields with the comment
`# Claude Code command extensions (ISS-211)`, covering `argument_hint` and
`model`. `allowed_tools` is spelled `allowed-tools` in phase markdown
frontmatter. Those are slash-command frontmatter fields. Anthropic has since
merged custom slash commands into Agent Skills, and the "configure an agent for
a job" shape now lives in the subagent definition.

So the schema was modelled on the right thing at the time, and the ecosystem
moved out from under it. `max_tokens` is already a dead command-era field the
platform rejects at parse time (`workflow_definition.py:336-359`).

### 2. Most of what a phase declares is never applied

`ExecutablePhase` has exactly one production construction site,
`ExecuteWorkflowHandler._build_executable_phases`. Anything not passed there is inert by
construction. Verified inert: `input_artifacts`, `execution_type`,
`argument_hint`, and `allowed_tools`.

`allowed_tools` is the consequential one. `_build_agent_config_from_phase`
constructs `AgentConfiguration` with only
`provider`, `model` and `allow_delegation`, so `allowed_tools` keeps its default
of `()`. The `if phase.agent_config.allowed_tools:` guard in `_wiring.py:309`
therefore never fires, `--tools` is never emitted, and every phase inherits the
full toolset. Three consequences follow:

- #964 shipped a closed-vocabulary validator that rejects `bash` for `Bash` at
  authoring time, enforcing a restriction that is never applied.
- `UnsupportedToolPolicyError` and `apply_tool_policy_to_prompt`
  (`_wiring.py:425-433`) are unreachable.
- Artifact injection is unconditional, so every phase receives every completed
  prior phase's output regardless of `input_artifacts`.

That last point makes this a context-efficiency defect and not only a
correctness one: the two knobs that would make a phase narrow are the two that
are dropped, at the same line. #1039 names two of the four fields; it is wider
than it says.

### 3. The two harnesses restrict along orthogonal axes

Measured on Claude Code 2.1.257 and codex-cli 0.147.0. Each harness implements
exactly one axis and has no vocabulary for the other:

- **Claude** enforces WHICH TOOLS EXIST (`--tools`, availability) and imposes no
  filesystem boundary. Under `--dangerously-skip-permissions` a Write landed
  outside the working directory.
- **Codex** enforces WHERE THE PROCESS MAY WRITE at the kernel level and has no
  tool vocabulary at all; it rejects tool-name policies by design (#1009). In
  the same run that had an unrestricted shell, a write outside the workspace was
  blocked.

Neither guarantee is expressible in the other's vocabulary. The two providers
are not unequal along one axis, they are **uncomparable**. Any schema offering a
single `restriction_level` enum, or treating `tools` as a neutral field, asserts
an ordering that does not exist.

This is the constraint that decides the rest of this ADR.

### 4. The domain owns the harness wire protocol at both ends

There is no agent-execution port. `AgentRunSpec` and `RunExecutor`, named as the
single contract in ADR-068, return zero matches in code; the six hits are all in
`docs/`. The seam is
`CommandBuilder = Callable[[ExecutablePhase, str], list[str]]`
(`processor_types.py:69`): the domain hands down an argv list and parses raw
stdout itself.

`syn-domain` is the largest concentration of harness-specific code in the
repository, ahead of the adapters and the composition layer. It holds 1377 lines
of vendor wire-format parsing, including a regex over the codex binary's own
tracing module names (`CodexStreamProcessor.py:139`).

Meanwhile agentic-primitives does not own invocation at all.
`harnesses/__init__.py` states twice that `HarnessPlugin` covers transcript
extraction and "never launch or auth". There is no `-p`, no `codex exec` and no
`stream-json` anywhere in the submodule.

So the boundary is inverted relative to the rule in AGENTS.md: the domain
depends on a format at both ends, rather than on a port.

## Decision

### D1. Split the document by who owns the guarantee

**Orchestration is neutral and stays here.** Phase ordering, artifact chaining,
budgets, wall-clock limits, cost, sessions, events. Every harness honours these
because the platform implements them, not the CLI. This is the same set AGENTS.md
already assigns to this repository, and it is the envelope APSS EXP-V1-0005
defers to its section 13 and has not built.

**The agent block adopts the shape of APSS EXP-V1-0005**: `harness`, `model`,
`skills`, `system_instructions`, `tools`, `mcp`, `subagents`, `allow_delegation`,
`from`. That field set is already harness-aware, and the standard's conformance
corpus validated 18 real Syntropic137 workflows against it.

The precedent is Terraform, which is the most successful multi-backend
declarative tool and defines zero neutral resource types. Its neutrality is the
lifecycle, the type system, the graph and the state; every semantic field is
namespaced to its provider. It makes no portability claim, so it never lies.

### D2. Every harness-sensitive field carries an enforcement tier

A field is declared once. What differs per harness is what the platform promises
about it:

| tier | meaning | example |
|---|---|---|
| `enforced` | the harness guarantees it | Claude + `tools` |
| `advisory` | expressed, NOT enforced, and normatively not a guarantee | a tool grant carried in a codex prompt |
| `unsupported` | refused at authoring time, naming harness and field | codex + `tools` |

`advisory` follows MCP's precedent for tool annotations, which the specification
normatively requires clients to treat as untrusted rather than as a promise. An
advisory field must be labelled as such wherever it is surfaced; a soft promise
presented as a guarantee is the defect this ADR exists to prevent.

This is what lets the definition EXPRESS tools and MCP for every harness while
the platform never claims a guarantee it does not hold.

### D3. Refuse at authoring time, and verify at runtime

Every system surveyed validates at both ends, and the ones with documented pain
picked only one. Terraform pairs plan-time validation with a post-apply
consistency check that treats a falsified prediction as an error. MCP negotiates
only at connect time, and the ecosystem had to build an out-of-band capability
matrix because negotiation did not answer the question.

So: a phase declaring an `unsupported` combination is rejected when the workflow
is created, beside the tool-vocabulary check #964 already put there. And a phase
additionally verifies at run time that it received what it declared. The two are
not redundant; the first is cheap and early, the second catches the case where
the guarantee was not actually delivered.

### D4. State the absence rule

A missing property means absence, not a default with different meaning, and
unknown properties are ignored rather than rejected. LSP writes this down in
both directions and it is why LSP survived a decade of capability growth. MCP
did not, and broke strict servers when it added a capability. Note that
EXP-V1-0005 already distinguishes absent from empty for `tools` and `mcp`, which
is the same instinct.

### D5. A schema field must apply or refuse

A field may exist only if there is a code path that applies it or refuses it.
Enforce this as a fitness function. This repository already runs fitness
functions, and this is the rule that would have prevented every inert field in
section 2.

### D6. The format goes to APSS; the translation stays here, behind a port

The recipe format belongs in APSS, because it is shared and it is their
standard. The translation from a phase definition to an argv line stays in this
repository behind a port, satisfying the AGENTS.md rule without paying the
submodule delivery tax while the design is still moving.

Do not move invocation into agentic-primitives yet. A change there reaches a
running workspace only after merge, image build, the protected release channel,
and a `PINNED_DIGESTS` bump here. That cost is worth paying for a stable
contract and not for one still being designed.

## Consequences

- **#1039 must be widened and done first.** Wiring the four inert fields through
  the single construction site is the whole feature; everything else in this ADR
  is unobservable until it lands.
- **The codex tools refusal becomes reachable**, and should move from dispatch
  to workflow creation so the asymmetry is visible before money is spent on
  provisioning.
- **Adopting EXP-V1-0005 is blocked on two things upstream.** Their #127 records
  that no conforming Python loader exists and that reimplementing violates their
  own requirement R4; `syn-domain` is Python. Their #129 is the same defect as
  our #1052: `harness: claude` with `tools: [shell]` validates clean in their own
  shipped example. We would be the standard's first real consumer, so D2 is a
  contribution upstream rather than a private workaround.
- **The standard is 0.3.0, not 0.2.0.** `backwards_compat = false`, not
  promoted, no changelog, and an open pre-adoption punch list. Adopt the shape,
  track the version deliberately.
- **The escape hatch will try to eat the abstraction.** Every system surveyed
  that offers a provider namespace sees it absorb each new feature, because that
  is always the cheapest path. D5 is the counterweight.

## Open questions

- Whether `subagents` can carry the experimentation fan-out. EXP-V1-0005
  validates it but does not execute it, and states that the standard does not
  define how a consumer should orchestrate delegation. The permission-boundary
  semantics (a subagent's resolved tools and mcp must be within the delegator's)
  are useful regardless.
- MCP server declarations are deliberately out of scope here. EXP-V1-0005's
  `mcp` field declares policy only, never server definitions. Per-phase MCP is
  the MCPC work (okrs-51p.1) and should be designed once this format is settled.
- Turn limits. Claude has `--max-turns`, which is enforced and fails loudly, but
  is undocumented in `--help` for 2.1.257. Codex has no equivalent. This is a
  `tools`-shaped problem and D2 covers it, but it needs a decision on whether an
  absent turn limit is expressible at all.
- The capability matrix was measured on the macOS host, not inside the Linux
  workspace image. The sandbox and network results depend on the host kernel and
  MUST be re-measured in-container before anything is built on them. One result
  is already anomalous: codex `--sandbox` did not block network egress in any
  configuration tested, including with `network_access=false`, while the
  standalone `codex sandbox` subcommand did. Cause undetermined. This compounds
  #1049, where the declared network settings do not describe the runtime.


## Implementation notes (2026-09-01, #1039)

D3, D4 and D5 are implemented. D1, D2 and D6 are untouched and remain
proposals. Three things were learned by building it that change what the ADR
above says, recorded here rather than left to contradict it.

### `input_artifacts` cannot be applied, only checked

Section 2 lists it among the fields that are "never applied" as though wiring
it were the fix. It is not, and this was established by measurement over all 22
authored multi-phase workflows before anything was built:

- injection is keyed on PHASE IDS (`_substitute_inputs`, `_build_context_appendix`)
- the declaration names ARTIFACT TYPES (`input_artifacts` -> `input_artifact_types`)
- the intersection of the two vocabularies across the corpus is the EMPTY SET.
  0 declared inputs equal a phase id; 31 equal a prior phase's output type.

Filtering phase outputs by the declaration would therefore match nothing and
give every phase an empty context. The field is now validated instead: every
declared type must be produced by an earlier phase or supplied by a workflow
input, else the workflow is refused.

**Open question this produces.** Making it a checked assertion stops it being
inert; it does NOT make phases context-efficient, because every phase still
receives every prior phase's output. Narrowing needs a phase-id-keyed field -
something like `inputs_from: [phase-id]` - designed deliberately rather than
retrofitted onto a type graph. Not built.

**Second open question, raised in review.** The validator treats workflow INPUT
NAMES as satisfying artifact TYPES, which are different namespaces; it is a
pragmatic join, not a real one. The alternative is an explicit `artifact_type`
on input declarations. Unresolved, and it belongs here rather than in the
implementation.

### D5 must count display as a fate

"A schema field may exist only if there is a code path that applies it or
refuses it" is too narrow as written. Applied through the AGENT COMMAND is what
it implies, and by that reading `argument_hint` is inert and should be deleted -
which is exactly the conclusion reached, and it was wrong. The dashboard renders
it (`PhasePromptEditor.tsx`), and the domain describes it as display metadata
for `$ARGUMENTS`.

So the rule is: applied, refused, validated, or displayed. The fitness function
enforces all four, and a field classified as displayed must name the UI source
that renders it.

### Refusal has to happen at both ends, not just at authoring

D3 says "refuse at authoring time, and verify at runtime". Building it showed
the runtime half is not optional and not merely a double-check: a template
stored before a rule existed is rehydrated from its historical
`WorkflowTemplateCreated` event and NEVER sees the authoring validator. The
population most likely to carry a bad declaration is precisely the one
authoring-time refusal cannot reach.

There are three entry points - HTTP, GitHub trigger, and the execution boundary
itself - and each needs the check for a different reason. The trigger path is
the one that bites: it acknowledges a dispatch before any validation, so a
refusal inside the async task leaves a record claiming a run that has no
execution and never will.
