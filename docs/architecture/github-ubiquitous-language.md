# Ubiquitous Language: github

## Purpose

The vocabulary of the `github` bounded context. These words have exactly these
meanings in code, in the API, in the CLI and in conversation. Where a term here
disagrees with any other document, this one is canonical.

For event-sourcing patterns - Event, Aggregate, Projection - see
`es-glossary.md`. A term belongs here when it names something this context's
users talk about, and there when it names a mechanism the platform provides.

Every bounded context has one of these, named
`<bounded-context>-ubiquitous-language.md`. See AGENTS.md, "Ubiquitous Language".

---

## Installation

One GitHub App installation on one account, and the platform's right to act as
it. Registered by `AppInstalled`, ended by `InstallationRevoked`, temporarily
withdrawn by `InstallationSuspended`.

Holds the permission grant that every token is minted from. A token can never
carry more than its Installation holds.

## Token

A short-lived installation access token minted for a specific purpose, recorded
by `TokenRefreshed`. Scoped DOWN from the Installation's grant when the caller
asks for less, which is how a Phase that must not publish is prevented from
publishing.

Expires in roughly an hour, which is why refresh is a domain event and not an
implementation detail.

## Trigger Rule

A standing instruction to run a Workflow when a GitHub event matches its
conditions. Registered by `TriggerRegistered`, removed by `TriggerDeleted`.

Statuses include `ACTIVE` and `PAUSED`. A Trigger Rule fires only while
`ACTIVE`: `can_fire()` returns `status == ACTIVE`, so pausing genuinely stops
it.

## Pause and Resume

Pausing a Trigger Rule stops it firing (`TriggerPaused`); resuming returns it to
`ACTIVE` (`TriggerResumed`). Both are enforced, not advisory.

**`resume` here is not `resume` in `orchestration`**, where it means continuing
an Execution that did not finish by starting a new one. This is un-pausing the
same Trigger Rule. One meaning per context is the rule, and these are two
contexts.

## Fire

One match of a Trigger Rule against an event, counted (`fire_count`) and
recorded by `TriggerFired`. Counting matters because the count feeds the safety
guards that stop a rule firing in a loop.

Blocked instead of fired when a guard refuses it (`TriggerBlocked`).

## Dispatch

The act of starting a Workflow because a Trigger Rule fired, completed by
`TriggerDispatchCompleted` or `TriggerDispatchFailed`.

A Fire is the decision; a Dispatch is the consequence. They are separate events
because either can happen without the other succeeding.

### Dispatch record status

Each Fire leaves a dispatch record, the to-do item `WorkflowDispatchProjection`
works from. Its `status` says how far the Dispatch got:

| Status | Means | Offered again? |
|---|---|---|
| `pending` | Fired, not yet offered to the dispatcher | Yes |
| `paused` | Admission refused it - a deploy, a full disk (#1387, #1560) | Yes, once admission re-opens |
| `queued` | Handed to the dispatcher, which has not yet said its execution is durable (#1707) | Yes, unless this process still holds the start |
| `dispatched` | The dispatcher confirmed the execution exists | No |
| `failed` | It cannot start: no workflow, over budget, or the start raised before its execution existed | No |

**`queued` is not `dispatched`.** A queued start waits in the dispatcher's
memory for an execution slot, so a restart or a crash takes it with it. A
record that said `dispatched` at that point was a trigger nothing would ever
run. A re-offer of a `queued` start that did become durable is refused by the
execution stream's NoStream write, and that refusal counts as started.

`paused` here is a dispatch record status, not the Trigger Rule's `PAUSED`
above: a paused record is one Fire held back, not a rule that stopped firing.

## Normalized Event

A GitHub event reduced to the shape the pipeline acts on, whatever source it
arrived from - webhook, Events API poll, or Checks API poll. The normalisation
is what lets one pipeline treat three sources identically.

## Dedup Key

The content-derived identity of a logical event - a commit SHA, a PR number, a
check run id - used to process it exactly once no matter how many sources
delivered it.

Deliberately NOT a delivery id: two sources give one logical event two delivery
ids, and keying on those would process it twice.
