# Ubiquitous Language: artifacts

## Purpose

The vocabulary of the `artifacts` bounded context. These words have exactly
these meanings in code, in the API, in the CLI and in conversation. Where a term
here disagrees with any other document, this one is canonical.

For event-sourcing patterns - Event, Aggregate, Projection - see
`es-glossary.md`. A term belongs here when it names something this context's
users talk about, and there when it names a mechanism the platform provides.

Every bounded context has one of these, named
`<bounded-context>-ubiquitous-language.md`. See AGENTS.md, "Ubiquitous Language".

---

## Artifact

Something a Phase produced and the platform kept, identified by a UUID and
owned by the Execution that produced it. Created by `ArtifactCreated`, its
bytes stored separately and recorded by `ArtifactUploaded`.

An Artifact is a DIRECTORY of files, not a single file. That is the unit
mistake worth avoiding: a count of Artifacts is not a count of files, and the
two cannot be compared. See `orchestration`'s Inherited Phase, which carries
artifact ids and resolves them to files.

## Phase Output File

One file inside an Artifact, carrying its content and the workspace-relative
path it occupied (`source_path`). The path is optional only because Artifacts
created before `ArtifactCreated` v5 do not have one; a missing path means
"flat name only", never "guess a path".

Carries no artifact id of its own, which is why a caller cannot tell from the
files alone which of several requested Artifacts resolved - see issue #1460.

## Primary Deliverable

The one Artifact of a Phase that represents its result, flagged
`is_primary_deliverable`. Distinguishes the thing a downstream Phase is meant
to read from the incidental files beside it.

## Ownership by Execution

An Artifact is filed under the Execution that produced it, and the query that
retrieves it filters on that execution id. A resumed Execution inherits
Artifacts it did not produce, so the inheriting side must ask the Execution
that actually produced each one rather than its own id - the defect behind
#1462.

## Creation Time Recovery

`ArtifactCreationTimeRecovered` exists because some Artifacts were stored
without a trustworthy creation timestamp and it was reconstructed afterwards.

**Unclear:** whether recovery is still reachable for new Artifacts or is purely
historical. The event is present and the code path is not obviously dead;
someone who knows should either document the trigger here or delete the event.
