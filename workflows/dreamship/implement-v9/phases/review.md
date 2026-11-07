---
model: gpt-sol
timeout-seconds: 3000
---

# Review the PR the previous phase opened

$ARGUMENTS

## Skills for this phase (load each one in full, first)

Read each skill's `SKILL.md` with its own command, `cat /workspace/.agents/skills/<name>/SKILL.md`:
- one file per command;
- no `rtk` prefix;
- never several files in one loop.

A longer output is cut in the middle before you see it, and a skill you have read only half of is not loaded. Then run `wc -l` on the files.

Your first output line must be `SKILLS LOADED:`, followed by each name with its line count. Name any skill you could not load, with the reason.

- `software-leverage-review`
- `testing`
- `security`
- `architecture`
- `canonical-knowledge`
- `red-gates-and-fitness`
- `code-quality-assurance`
- `vertical-slices`

Judge the change against these skills, and name the skill behind each finding.

The implement phase ran `software-leverage-review` and posted its report on the PR. Check that its headline findings were fixed, and list any that were not.

## Review by trying to falsify, not by reading the diff

Check the branch out and RUN things. A review that only reads the diff catches
style and misses behaviour.

- **Does the test actually test the thing?** Mutate the implementation so the
  claimed behaviour is wrong, and confirm the new test FAILS. A test that still
  passes under a mutation proves nothing, and this is the most common defect in
  agent-written tests in this repo. Report any test that survives mutation as a
  BLOCKER.
- **Does it replay?** If the change touches an event type, an envelope, a
  serialized shape, or an identifier, find this repo's pre-change fixtures and
  confirm a record written before the change still decodes. A replay break is a
  BLOCKER.
- **Did the gates really pass?** Re-run them yourself. Do not trust the report's
  transcript.

## Security, explicitly

Security is first-class on DreamShip. Check at minimum:

- **The content rule.** Does any new field put content, rather than a reference,
  on a path that reaches the event log? An append-only log cannot un-write a
  payload, so this has to hold on the way in.
- **Compartment isolation.** Nothing may leak out of a Compartment. Does any new
  lookup or projection cross a compartment boundary, or match on a label that is
  not scoped to one?
- **Derived identifiers.** Is any new id an unkeyed hash of user text? That is
  reversible, and it is a disclosure even when every field is compliant.
- Secrets in code or logs, unvalidated input at a trust boundary, and any mock
  missing `assert_test_env!()`.

## Output

Write to `artifacts/output/deliverable.md`. THAT FILE IS THE DELIVERABLE and it is
the only thing this phase owes anyone.

Then, BEST EFFORT ONLY, try to post the same text as a PR comment with
`gh pr comment`. If that fails for any reason - no PR for the branch, a denied
permission, a network error - say so in one line at the end of the deliverable and
REPORT SUCCESS ANYWAY. Do not retry it, do not try to create a PR, and do not treat
it as a reason to fail.

This is not laxity. A review that finished its work and could not deliver a copy of
it has still done its job, and failing the phase there throws away the review, stops
the remediate phase from ever running, and reports the whole run as a refusal - which
reads as "the code was rejected" when nothing was. Nine runs died exactly that way.
The artifact is collected either way.

Separate **BLOCKERS** from **NON-BLOCKING FINDINGS**, blockers first. A blocker
is: wrong behaviour, a test that survives mutation, a replay break, a security
finding, or a claim in the PR body that is not true. Anything else is
non-blocking. Say so rather than inflating it.

For each finding give the file and line, what is wrong, and the concrete input or
state that makes it go wrong. "Consider extracting this" is not a finding.

End with one line, exactly one of: `VERDICT: MERGE` or `VERDICT: BLOCKED`.
