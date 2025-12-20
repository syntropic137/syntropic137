# Manual Testing Checklist

Run AFTER automated tests pass.

This checklist covers the 5% that automated tests can't verify:
- UI/UX correctness
- Visual appearance
- Cross-system integration
- Real-world workflows

Expected time: 5-10 minutes

## Prerequisites

- [ ] All unit tests pass: `just test-unit`
- [ ] All integration tests pass: `just test-integration`
- [ ] Dev environment running: `just dev-fresh`
- [ ] No errors in console

## Setup Verification

- [ ] Dashboard loads at http://localhost:5173
  - [ ] No console errors (check DevTools)
  - [ ] UI renders correctly
  - [ ] Navigation works

- [ ] Backend loads at http://localhost:8000/docs
  - [ ] API docs render
  - [ ] Health endpoint returns 200

- [ ] Database is accessible
  - [ ] Can connect to PostgreSQL
  - [ ] Tables exist

## Workflow Execution

- [ ] Can see workflow list
  - [ ] At least 1 workflow visible
  - [ ] Workflow details display

- [ ] Can trigger workflow execution
  - [ ] Execute button works
  - [ ] Execution starts (see spinner/loading)
  - [ ] Status updates in real-time

- [ ] Events appear during execution
  - [ ] Event stream shows activity
  - [ ] Events have correct data
  - [ ] Timeline updates

- [ ] Execution completes
  - [ ] Status changes to "completed"
  - [ ] Duration displayed
  - [ ] Tokens/cost shown

- [ ] Artifacts are available
  - [ ] Artifacts section populated
  - [ ] Can download artifacts
  - [ ] Content is correct

## Error Handling

- [ ] Errors display correctly
  - [ ] Error messages are clear
  - [ ] UI doesn't break on error
  - [ ] Can recover from errors

- [ ] Long-running workflows
  - [ ] Progress indicator works
  - [ ] Can cancel execution
  - [ ] Status updates accurately

## Edge Cases

- [ ] Multiple concurrent workflows
  - [ ] Can run 2+ workflows simultaneously
  - [ ] Events don't mix up
  - [ ] Each workflow tracked correctly

- [ ] Session tracking
  - [ ] Session list updates
  - [ ] Can view session details
  - [ ] Metrics are accurate

## Performance

- [ ] Dashboard responsive
  - [ ] UI doesn't lag
  - [ ] Real-time updates smooth
  - [ ] No memory leaks (check DevTools)

- [ ] API responsive
  - [ ] Queries return quickly (<1s)
  - [ ] No timeout errors

## Sign-Off

- [ ] All checks passed
- [ ] No console errors
- [ ] No UI glitches
- [ ] No data inconsistencies
- [ ] **ZERO defects found**

## If Defects Found

1. Document the bug in `ISSUES.md`
2. Write regression test
3. Fix the bug
4. Verify fix with test
5. Re-run this checklist

**DO NOT proceed to production until checklist is clean.**
