# Mutation evidence for #1916 (PR #2078)

Twenty patches, one per meaningful check in non-test source, regenerated
against the head that merged `origin/main` (the earlier 01-16 set had gone
stale and was dropped). Each was applied, asserted applied (non-empty
`git diff`), killed locally by its named tests, and reversed; every named
test passes on clean HEAD. `killers.tsv` maps patch to killing node ids.

Several killers are `integration` tests on real Postgres (16-20, and the
store tests), so dispatch with Docker (the default):

```
just mutation-evidence 2078 "$(cat ids.txt)"
```

where `ids.txt` is the space-separated union of `killers.tsv`'s second column.

| Patch | Bug |
|---|---|
| 01-unsettled-sandbox-writer-stopped | recovery resumes and stops the writer of a spool with no terminal fact |
| 02-no-fence-before-resume | no lease fence before resume |
| 03-no-fence-after-slow-resume | no fence after a slow resume, so a stale worker stops the writer |
| 04-exclusive-presumed-from-fencing | `exclusive` from the run state, no stop-and-confirm |
| 05-raising-stop-yields-exclusive | a raising `stop_writers` counts as confirmed |
| 06-closing-fence-outage-skips-pause | a store error at the closing fence leaves the sandbox running |
| 07-stale-worker-pauses-new-owners-sandbox | a worker that lost the lease still pauses the sandbox |
| 08-removal-kills-live-writer | retention kills a sandbox whose writer still runs |
| 09-upload-failure-kills-sandbox | a failed archive kills instead of leaving it paused |
| 10-docker-port-for-remote-row | an E2B row is opened with the Docker port |
| 11-claims-unreachable-backends | the worker claims backends it holds no port for |
| 12-release-before-mark-drained | release (kill) before `mark_drained` |
| 13-advance-before-closing-pause | progress recorded inside the context, giving the lease up before the pause |
| 14-missing-executor-accepted | a remote row without `executor_id` validates |
| 15-profile-backend-mismatch-accepted | profile and backend may disagree |
| 16-claim-ignores-backend | the store's claim ignores the backend filter |
| 17-unsettled-remote-spool-claimable | the store leases an unsettled sandbox spool |
| 18-byte-quota-spans-backends | the byte quota counts and evicts across backends |
| 19-count-ceiling-evicts-running-sandbox | the count ceiling evicts a non-settled sandbox |
| 20-runtime-wires-docker-only | the runtime drops the remote recovery port (the issue's negative control) |
