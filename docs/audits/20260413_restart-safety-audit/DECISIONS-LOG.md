# Decisions & Questions Log

Items flagged during implementation for human review. Each entry is
something I was unsure about or that felt like it needs a judgment call.

---

## Open Questions

(none yet)

---

## Decisions Made (review when convenient)

| # | Date | Context | Decision | Confidence | Notes |
|---|------|---------|----------|------------|-------|
| 1 | 2026-04-14 | ESP PR #274 backwards compat | Skipped handle_event() backwards-compat shim | High | User confirmed: unreleased library, breaking changes fine |
| 2 | 2026-04-14 | read_all backwards semantics | Changed from_global_nonce=0 to sys.maxsize for reverse reads | Medium | Copilot flagged the original approach. sys.maxsize works with the MemoryEventStoreClient filter (global_nonce <= from_global_nonce). Need to verify gRPC backend handles this too. |
| 3 | 2026-04-14 | Box::leak in Rust VSA rule | Replaced with owned HashSet<String> | High | Clear improvement, no tradeoffs |
| 4 | 2026-04-14 | TYPE_CHECKING in Rust parser | Added indentation-based block detection | Medium | Line-based heuristic, not a real AST. Works for standard formatting but could miss unusual indentation. Python fitness module is authoritative; Rust rule is best-effort. |
| 5 | 2026-04-14 | reportPrivateUsage in ReplaySafetyChecker | Added public properties/methods to SubscriptionCoordinator instead of suppressing pyright | High | Cleaner than type: ignore comments. Properties: projections, is_catching_up (r/w), live_boundary_nonce (r/w). Method: dispatch_event(). |
| 6 | 2026-04-14 | Phase A1 dispatch dedup | Deferred A1 (execution_id dedup in ExecuteWorkflowHandler) | Medium | The ProcessManager conversion (B1+B2) already prevents the replay storm - process_pending() is never called during catch-up. A1 adds defense-in-depth but requires understanding the execution repo load/query pattern. Ship the structural fix first, add A1 as follow-up. |
| 7 | 2026-04-14 | Phase A4 dedup fallback | Chose fail-open with ERROR log instead of refusing to start | Medium | Fail-closed (refuse to start) would break dev environments that don't run Postgres/Redis. Kept InMemoryDedupAdapter but upgraded logging from warning to error. Production should always have a durable backend - the ERROR log makes it obvious. |
