# Why every gate passed

$ARGUMENTS

Read `artifacts/input/bisect.md` first.

This is the phase the workflow exists for. Everything before it describes what
broke. You answer the only question that changes the future: **the tests, the
reviews and the gates all passed. Why?**

You are running on a different model from the one that wrote the code and the
gates, deliberately. The model that built a test is the worst judge of what that
test does not check.

## The rule: "add a test" is not an answer

Writing "this needs a regression test" is cheap and nearly worthless. Assume a
test probably already exists near the defect. The interesting question is why it
did not fire, and the answers cluster into a small number of shapes:

**1. The test points the wrong way.** It exists, it binds the right two things,
and it asserts the converse of what was needed. A real example from this
repository: a test bound a prompt to its parser by pasting the whole prompt
after a known-good report and asserting the verdict survived. That asks "can the
instructions corrupt a good answer?" It never asked "does following the
instructions produce a good answer?" The binding existed and pointed backwards.

**2. The fixture cannot reach the code.** The test builds an input that fails an
earlier guard, so it passes for a reason unrelated to its name. A near-miss
input that fails safe certifies an open class as closed.

**3. The gate does not run.** An unmarked test module, a suite no CI job
invokes, a job whose result nothing checks. A green gate over nothing is worse
than no gate, because it is trusted.

**4. The scope verified is narrower than the scope that runs.** Someone ran the
suite for two packages when CI runs three, or one marker when CI runs two.

**5. The contract has two sides and nothing binds them.** A format is published
in one file and parsed in another. Each side is tested against fixtures it
invented. Neither is tested against the other.

**6. Nothing could have caught it at this layer.** A legitimate answer. Some
defects only appear against real infrastructure, real concurrency, or real
agents. Say so, and say which layer WOULD have caught it - that is the finding.

## What to do for each regression

Work from the mechanism the previous phase identified.

1. **Find the gates that cover that code.** Search for tests touching the file
   and the function. Search the fitness rules. Check whether a CI job runs them.
   List what you find, by path.
2. **For each, say why it passed.** Read the assertion. Not the name - the
   assertion. Map it to one of the shapes above.
3. **Then say what would have caught it**, concretely enough to implement:
   the file, the input, the assertion. Not "test the parser handles bad input" -
   rather "extract the example block from the rendered prompt and feed it
   through `AgentVerdict.from_agent_text`, asserting a non-UNREADABLE verdict".

## Prescribe tests that cannot rot the same way

A prescription that repeats the original blind spot is worse than none, because
it will be merged and trusted. Two properties to aim for:

- **Consume the published artifact, not a copy of it.** If a format is published,
  the test must extract it from where it is published. A test that hardcodes its
  own copy of the format passes forever after the real one drifts.
- **State how the test can fail.** Name the mutation: what single change to the
  production code makes this test go red? If you cannot name one, the test may
  assert nothing. This is the same discipline the implement phases are held to,
  and it applies harder here because these tests are being added specifically to
  catch a thing that already got past everyone.

## Also check the gates that are not tests

Some of the shapes above are not about tests at all:

- Does the deploy runbook have a step that would have surfaced this?
- Does the post-deploy verification exercise the thing that broke? A check that
  a phase reaches `running` proves the workspace built; it cannot prove a phase
  can finish and report.
- Is there a preflight that could predict it from the diff?

A process change is often cheaper and more durable than a test, and this phase
is the right place to notice that.

## Write to `artifacts/output/autopsy.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish, even if the
finding is "nothing could have caught this" - that is a deliverable.

Per regression:

1. **Gates that cover the code** - paths, and whether each ran.
2. **Why each passed** - the assertion, and which shape it matches.
3. **The prescribed test** - file, input, assertion, and the mutation that
   makes it fail.
4. **Process changes**, if a test is the wrong instrument.

Close with the **shape tally**: how many of this window's regressions were each
shape. Three windows of that tally tell you which gate discipline is weakest,
which no individual retrospective can.
