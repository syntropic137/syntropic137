# E2E Testing Execution Prompt

Copy this entire prompt to a new agent session:

---

## Task: Complete E2E Testing for Projection Checkpoint Migration (ADR-014)

**EEM** (Enter Execute Mode)

### Context

We've migrated the AEF from a legacy global checkpoint system to per-projection checkpoints (ADR-014). All code changes are complete and committed. **Your task is to run E2E tests to validate everything works.**

**Worktree:** `/Users/neural/Code/AgentParadise/agentic-engineering-framework/worktrees/realtime-projection`
**Branch:** `refactor/realtime-projection-architecture`

### What Was Done

1. ✅ ES Platform: New `CheckpointedProjection`, `SubscriptionCoordinator`, `PostgresCheckpointStore` (PR #85 merged)
2. ✅ AEF: 7 domain projections migrated to `CheckpointedProjection`
3. ✅ AEF: New `CoordinatorSubscriptionService` replaces legacy service
4. ✅ QA: All 481 tests pass, lint/type/format clean

### Your Task: M7.4 - E2E Testing

1. **Start the dev stack:**
   ```bash
   cd /Users/neural/Code/AgentParadise/agentic-engineering-framework/worktrees/realtime-projection
   just dev-fresh
   ```

2. **Test via browser** (use browser automation tool):
   - Navigate to `http://localhost:5173`
   - Create a workflow or use existing
   - Run the workflow
   - Verify execution detail shows live updates (WebSocket)
   - Check metrics update

3. **Verify backend:**
   - Check logs for checkpoint saves: `just dev-logs`
   - Query PostgreSQL: `SELECT * FROM projection_checkpoints;`

4. **If issues found:** Debug and fix, then re-run QA (`just qa`)

5. **When E2E passes:**
   - Commit any fixes
   - Push branch and create PR
   - Report success

### Key Files (if debugging needed)

| File | Purpose |
|------|---------|
| `packages/aef-adapters/src/aef_adapters/subscriptions/coordinator_service.py` | New subscription service |
| `apps/aef-dashboard/src/aef_dashboard/main.py` | App startup (line 78-116) |
| `lib/event-sourcing-platform/docs/adrs/ADR-014-projection-checkpoint-architecture.md` | Architecture reference |

### Troubleshooting

**If `uv` hangs:**
```bash
pkill -9 -f "uv" && uv cache clean --force
```

**If imports fail:**
```bash
rm -rf .venv && rm uv.lock && uv lock && uv sync
```

### Success Criteria

- [ ] Dashboard loads with metrics
- [ ] Can run a workflow
- [ ] Live updates appear in execution detail
- [ ] No backend errors
- [ ] Checkpoints saved to DB

---
