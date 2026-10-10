# Ubiquitous Language: organization

## Purpose

The vocabulary of the `organization` bounded context. These words have exactly
these meanings in code, in the API, in the CLI and in conversation. Where a term
here disagrees with any other document, this one is canonical.

For event-sourcing patterns - Event, Aggregate, Projection - see
`es-glossary.md`. A term belongs here when it names something this context's
users talk about, and there when it names a mechanism the platform provides.

Every bounded context has one of these, named
`<bounded-context>-ubiquitous-language.md`. See AGENTS.md, "Ubiquitous Language".

---

## Organization

The top of the hierarchy: who the work belongs to. Created by
`OrganizationCreated`, removed by `OrganizationDeleted`.

Exists so cost, activity and repositories can be attributed to an owner rather
than floating free.

## System

A named grouping of Repos inside an Organization - a product, a service, a
deliverable. Created by `SystemCreated`, removed by `SystemDeleted`.

A System is how a question like "what did this product cost" becomes answerable:
it is the unit insights aggregate to.

## Insight

A learning-loop finding: a lesson about how to improve workflows, speed and
cost, aggregated across Organizations, Systems and Repos. Served by the
`/insights/*` routes and the `syn insights` command group (overview, cost,
activity heatmap).

Owner's decision (2026-10-09): "insights" is reserved for this meaning. A
number is an insight when it tells someone what to change in how work is done,
not merely how the running platform is behaving.

## Failed Day Count

On the activity heatmap, a day's `failed`: the Executions whose status is
`failed` and whose `completed_at` falls on that UTC day, selected and bucketed
by `completed_at` alone, so a run that started long before, or whose start was
never seen, still counts on the day it ended. Cancelled and interrupted runs
are not failures. Read from the
`workflow_executions` read model, never an aggregate.

## Repo

One repository the platform knows about, registered by `RepoRegistered` and
removed by `RepoDeregistered`. Assigned to a System by `RepoAssignedToSystem`
and detached by `RepoUnassignedFromSystem`.

A Repo may exist without a System. Assignment is a separate fact, so a
repository can be known before anyone decides what it belongs to.

## Connected Repo

A repository the platform can see and is expected to list: a **Repo** (one
`RepoRegistered` exists for it) **or** a repository some GitHub App
installation can reach, whether or not anyone registered it.

A Repo's identity is `(organization_id, provider, full_name)`, so two
organizations that each registered `acme/api` are two Repos, and a Gitea
`acme/api` is not the GitHub one. The uniqueness claim that enforces this
(`aggregate_repo_claim/claim_id.py`) hashes the triple **without folding
case**, so `Acme/API` and `acme/api` in one organization both register and are
two Repos as well, each with its own `repo_id` and possibly its own System.

Connected repos are therefore counted by Repo, and a registered one is
identified by its `repo_id`, never by its name: a name is not an identity here,
in any spelling.

A GitHub App installation reports no organization and no `repo_id`, so one of
its repositories can only be matched to a Repo by full name. That match folds
case, because GitHub itself treats `owner/name` case-insensitively, and it is
made only against a Repo whose `provider` is `github`, because no GitHub App
can reach a Gitea or GitLab repository however it is named. Case folding
belongs to this match alone, and never to a Repo's own identity.

A Repo so matched is one connected repo with the repository the App reaches; a
repository the App reaches that matches no registered GitHub Repo is a
connected repo of its own.

Two consequences, both deliberate:

- A name registered more than once - by several organizations, or twice in one
  organization in different cases - stays one connected repo per Repo. The
  App's single answer for that name applies to each of them, since the App is
  all that knows whether it can reach the name at all.
- A repository on another provider is never "Attached", and a partial App
  lookup leaves it "Not attached" rather than "Unknown": the answer does not
  depend on GitHub.

Not sources of their own:

- **A repo assigned to a System** - assignment is a fact about a Repo, so
  such a repo is already registered.
- **A repository named in an Execution's inputs** - an execution can name a
  repository the platform cannot reach and was never told about. Naming it
  does not connect it.

The dashboard's `/repos` page lists connected repos; one that the App reaches
but nobody registered shows as "Not registered" (feedback 29714ff9).

A connected repo's **privacy** is whatever GitHub reports for it when the App
reaches it, not the `is_private` recorded at registration: `syn repo register`
sends `is_private: false` for every repository, so a stored `false` is not
evidence of anything. For a Repo the App does not reach, a stored `true` still
means private (someone said so), but a stored `false` or none means the
privacy is **unknown**, and the page says so rather than showing it as public.

Installing the App does not register a Repo: no installation webhook issues
`RegisterRepo`. That is why this definition is a union and not just "a Repo".

## Repo Claim

An exclusive hold on a Repo, taken by `RepoClaimed` and released by
`RepoClaimReleased`.

**Unclear:** what the claim protects against. The aggregate exists
(`aggregate_repo_claim`) and the events are defined, but this vocabulary's
author could not establish from the code whether a claim prevents concurrent
Executions against one repository, prevents duplicate registration, or
something else. Whoever knows should replace this paragraph with the invariant
the claim enforces - and if nothing enforces it, the aggregate is a candidate
for the same treatment as the orchestration Pause.

## Words we do NOT use

- **Insight, for operational telemetry.** We do NOT call request latency an
  insight. API request latency (ADR-075), recorder drop counters, SSE health
  and build info are **Observability**: how the running platform behaves, Lane
  2 telemetry. They live under `GET /observability/*` and `syn observe`,
  never under `/insights` or `syn insights`. See "Observability" in
  `agent_sessions-ubiquitous-language.md`.
