# Proposal: gates-before-verify

**Status:** proposed
**Captured:** 2026-11-02
**Triggered by:** Anthropic's "AI-native SDLC playbook"
(claude.com/blog/the-ai-native-sdlc-playbook) and a walkthrough video of it
(youtube.com/watch?v=LoMOPj-lO8U). The playbook's point that applies here is that
deterministic checks run before any reviewer, and a reviewer judges only what a
command cannot.

## Question

If the repository's declared verification gates run as a command Phase
(ADR-078) on the implement head before `verify`, and a red gate goes to `fix`
without a codex pass, does `sdlc-implement-v4-precheck` reach READY faster and
more cheaply, with no more escaped defects?

## Why it matters (cost of not knowing)

- Today the verifier runs the gates itself. `verify.md` spends a section on
  finding and running them ("The gates belong to the repository you are
  verifying"), and `reverify` does the same. Every gate run is model time and
  quota spent reading test output, which no judgement is needed for.
- A red gate found by verify costs a full codex pass and then a fix round,
  about $2-3 and 27 minutes per round (`workflows/sdlc/implement-v7/EXPERIMENT.md`,
  Why).
- The decision it informs: whether the next implement version (v8) adds a gate
  phase, and whether ADR-078's "not in v1" items (D8 head handoff, typed
  verdict) are worth building now.

## Prerequisites (FOCUS: Capability readiness fails today)

ADR-078 v1 (#2141, PR #2162) cannot run this experiment as it stands:

1. **D8.** A command Phase sees the Execution's start pins, not the head an
   earlier Phase pushed. Gating implement's change needs the typed, recorded
   head handoff listed under "Not in v1".
2. **Routing.** A failed command Phase fails the run (D5, `gate`). The design
   needs "red goes to fix". Two options, decided in a design note before the
   hypothesis is written:
   - (a) a typed verdict from a command Phase (`requires_verdict`, "Not in v1"),
     so `blocked` advances to `fix` exactly as a review does
     (`workflows/sdlc/README.md`, `requires_verdict`);
   - (b) every step `allow_failure: true`, with `verify` reading
     `commands.json` and certifying nothing while a gate is red. This changes
     verify's prompt as well, so it is two variables, not one. Prefer (a).
3. **Inputs.** Neither `{{input}}` templating nor environment variables reach
   steps in v1. The gate list is the repo's `## Verification gates` block,
   so the steps can be fixed per target repo. That is acceptable for a pilot
   on syntropic137 only.

## Baseline to capture first (FOCUS: Underlying data)

Before writing the hypothesis, measure from the stored records of past runs,
not from what the current prompts say:

- For the last 20 completed v4-precheck and v3 runs: wall-clock and tokens
  spent inside verify/reverify on gate commands (from the archived native
  transcripts in Session Magic), and the share of `blocked` verdicts whose
  first finding was a red gate.
- If gate time is under ~10% of verify time and red-gate blocks are rare, the
  experiment is not worth running; record that and close the proposal.

## What running it would look like

- **Arms:** v4-precheck verbatim (control) vs v4-precheck plus one `gates`
  command Phase between `implement` and `verify`, and again between `fix` and
  `reverify` (treatment). Nothing else differs: diff the two YAMLs, and only
  the added phases may appear.
- **Primary metric:** repair rounds per run and median time to READY.
- **Secondary:** codex tokens per run, total cost (the command Phase itself
  costs 0, per ADR-078 D7).
- **Guardrail (quality):** escaped defects within the escape window, plus the
  verifier-seed-v1 catch rate and the false-block rate on clean controls,
  unchanged at k=3 (`docs/plans/20261026_eval-k-trials.md`, #2108).
- **Predictions (to be committed, not tuned):** to be written after the
  baseline. The working guess is fewer codex tokens per run and fewer full
  verify passes on red heads, with equal rounds overall, since a red gate still
  costs a fix round.
- **Invalidates the run:** unmatched bases between arms (the v7 vs
  v4-precheck A/B spent $52 and produced 0 scoreable pairs because of this),
  a VPS incident in one arm's window, or any change to a prompt in the
  treatment arm. Dry-run one pair first.

## What this proposal explicitly does NOT cover

- Changing which model verifies. Cross-family verification stays.
- Red-then-green test proof (a failing test at the base, passing at the head).
  It is a sibling proposal and needs the same D8 head handoff.
- Plan-then-cheaper-implementer. A separate proposal; it changes the model
  variable.

## What promotes this from proposal to experiment

All of: #2162 merged; the baseline above shows gate time or red-gate blocks
are material; the D8 head handoff and the routing decision (option a) are
implemented; the k-trials harness (#2108) can run verifier-seed at k=3.

## References

- `docs/adrs/ADR-078-command-phase.md` (on PR #2162): D5, D7, D8, Not in v1.
- `workflows/sdlc/implement-v4-precheck/` and its `EXPERIMENT.md`.
- `docs/experiments/CURRENT-BESTS.md`: v4-precheck provisional ADOPT; in 3 of
  6 slots verify certified a head whose real-service tests had never run.
- `docs/experiments/2026-10-20-end-to-end-replay.md` (E4): the end-to-end form
  a promotion needs.
