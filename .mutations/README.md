# Mutation evidence for #2161 (PR #2167)

Eighteen patches, one per meaningful check in non-test source. Each was
applied, asserted applied (non-empty `git diff`), killed locally by its named
tests, and reversed; every named test passes on clean HEAD. `killers.tsv` maps
patch to killing node ids. All killers are `unit` tests (E2B is the
`SandboxDouble`, Docker the memory backend), so Docker is not needed:

```
just mutation-evidence 2167 "$(cat ids.txt)" false
```

where `ids.txt` is the space-separated union of `killers.tsv`'s second column.

| Patch | Bug |
|---|---|
| 01-no-sandbox-spool-recorded | start_phase never records the sandbox (the issue's negative control) |
| 02-e2b-session-planned-as-local-spool | an E2B session starts with local-spool/1, so it gets a Docker row |
| 03-docker-session-planned-as-sandbox-spool | a Docker session starts with sandbox-spool/1 and loses its row |
| 04-projector-not-subscribed | the projector never subscribes to SandboxSpoolRecorded |
| 05-sandbox-start-projects-docker-row | a sandbox-spool/1 start also projects a Docker row |
| 06-row-routes-to-wrong-sandbox | the row names the executor as the sandbox |
| 07-repeat-record-not-idempotent | recording the same sandbox twice appends a second event |
| 08-second-sandbox-accepted | a second, different sandbox for one session is silently accepted |
| 09-docker-session-records-sandbox | a local-spool/1 or historical session accepts a sandbox spool |
| 10-finished-session-records-sandbox | a completed session still records a sandbox |
| 11-replay-forgets-sandbox | a rehydrated session forgets its sandbox, so a re-dispatch duplicates |
| 12-e2b-kit-mounts-volume | the E2B kit captures through a host volume mount |
| 13-e2b-kit-drops-capture-source | the E2B kit never captures (the pre-#2161 behaviour) |
| 14-service-forgets-spool-backend | the E2B service reports a Docker spool backend |
| 15-executor-id-not-the-label | the handle's executor id is not the label the sandbox carries |
| 16-event-accepts-extra-fields | the event accepts an undeclared field such as a reattach token |
| 17-docker-as-sandbox-backend | docker is accepted as a sandbox spool backend |
| 18-unroutable-executor-recorded | an executor id the spool row refuses is recorded, stalling the projector |
