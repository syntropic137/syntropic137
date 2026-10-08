# Ubiquitous Language Convention

> Moved verbatim from AGENTS.md / CLAUDE.md (CLAUDE.md diet, owner review). AGENTS.md keeps a one-line summary and a link here.


Every bounded context owns a vocabulary file. This is a DDD requirement, not a
documentation nicety: a bounded context is defined by the language that holds
inside it, so a context whose words are not written down has no boundary anyone
can check.

**Naming standard (enforced):**

```
docs/architecture/<bounded-context>-ubiquitous-language.md
```

The `<bounded-context>` segment MUST match the directory name under
`packages/syn-domain/src/syn_domain/contexts/`. The file name alone tells you
which context it speaks for, so no two vocabularies can be confused and an
orphaned file is detectable.

**Rules:**

| Rule | Why |
|------|-----|
| One file per bounded context, no exceptions | `ci/fitness/code_quality/test_ubiquitous_language.py` fails the build otherwise |
| The same word MAY mean different things in different contexts | That is the point of a bounded context. `github`'s `resume` is not `orchestration`'s `resume`, and each file says so |
| A term in the code MUST appear in its context's file | If you cannot name it, you do not understand it well enough to model it |
| Words we deliberately do NOT use get their own section | A reserved or rejected word is as load-bearing as an adopted one. `fork` is reserved in `orchestration`; `pause` was deleted from it |
| Genuine uncertainty is written down as **Unclear:**, with an issue | A vocabulary that hides its gaps lies about what the model knows |

**The ESP relationship:** the event-sourcing-platform submodule provides the
machinery (aggregates, projections, the VSA validator). It does NOT provide the
vocabulary. Each consuming bounded context owns its own file. ESP's own glossary
at `lib/event-sourcing-platform/docs/` covers event-sourcing mechanics
(aggregate, projection, checkpoint), not domain meaning.

**Start here:** [docs/architecture/README.md](./README.md) links
every vocabulary. [docs/architecture/es-glossary.md](./es-glossary.md)
covers the cross-cutting event-sourcing terms.

