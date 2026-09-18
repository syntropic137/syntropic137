# Classify by cause, and attribute the cost

$ARGUMENTS

Read `artifacts/input/gather.md` first. It names the JSON files holding the
corpus. Read those rather than re-fetching the API.

Your job is to turn a list of failures into a small number of **classes**, and
to say what each class cost. The next phases work on classes, not incidents.

## Rank by cost, not by frequency

The most frequent failure is usually the cheapest, because it fails early -
before any expensive phase ran. The failure worth fixing first is the one that
dies **late**, discarding work that already succeeded.

So for every class report both:

- **how often** it happened, and
- **how much it cost**, summed across its runs

and rank by cost. A class that happened twice and cost $27 outranks one that
happened nine times and cost $3.

**Also record WHEN in the phase sequence each class fires**, because that is the
mechanism behind the cost:

| fires | example | what it discards |
|---|---|---|
| before the agent runs | setup or injection crash | nothing, $0 |
| early, in the first phase | a gate rejecting a dirty tree | one cheap phase |
| after the work is done | an unreadable result marker | everything paid for |
| mid-work, budget exhausted | a phase timeout | everything not pushed |

A class that fires after the work is done is worth more attention than its
frequency suggests, and this table is how you show that rather than assert it.

## Quote one error verbatim per class

The exact string is what makes a class recognisable next time. A paraphrase is
not - two different bugs paraphrase to "workspace error". Quote the real text,
trimmed to the part that identifies it.

## Distinguish platform failures from task failures

Not every failure is a bug. An agent that correctly reported it could not do an
impossible task has not failed the platform, and counting it as one inflates the
number that should drive engineering.

Sort every class into:

- **platform** - the machinery failed: setup, gates, collection, parsing, budget
- **task** - the request was wrong, too big for a phase, or impossible
- **correct refusal** - the agent reported failure and the platform recorded it
  faithfully. This is the system WORKING, and it belongs in the tally with that
  label so nobody optimises it away.

If you cannot tell, say so and put it in a fourth bucket. A confident wrong
attribution here misdirects everything downstream.

## Write to `artifacts/output/classify.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish.

1. **The classes**, ranked by total cost, each with: count, total cost, when it
   fires, one verbatim error, and its platform/task/refusal label.
2. **The split** - what fraction of lost spend is platform versus task. One
   number, stated with its denominator.
3. **Any class that did not exist before this window**, if you can tell from the
   corpus alone. Flag it as a candidate regression and leave the proving to the
   next phase - do not go looking for a cause yet.
4. **What you could not classify**, with counts.

State plainly which numbers are measured and which are inferred. A reader must
not have to guess which is which.
