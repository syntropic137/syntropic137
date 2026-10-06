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

## Repo

One repository the platform knows about, registered by `RepoRegistered` and
removed by `RepoDeregistered`. Assigned to a System by `RepoAssignedToSystem`
and detached by `RepoUnassignedFromSystem`.

A Repo may exist without a System. Assignment is a separate fact, so a
repository can be known before anyone decides what it belongs to.

## Connected Repo

A repository the platform can see and is expected to list: a **Repo** (one
`RepoRegistered` exists for it) **or** a repository some GitHub App
installation can reach, whether or not anyone registered it. The two are
joined by full name, case-insensitively, so a repository that is both is one
connected repo.

Not sources of their own:

- **A repo assigned to a System** - assignment is a fact about a Repo, so
  such a repo is already registered.
- **A repository named in an Execution's inputs** - an execution can name a
  repository the platform cannot reach and was never told about. Naming it
  does not connect it.

The dashboard's `/repos` page lists connected repos; one that the App reaches
but nobody registered shows as "Not registered" (feedback 29714ff9).

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
