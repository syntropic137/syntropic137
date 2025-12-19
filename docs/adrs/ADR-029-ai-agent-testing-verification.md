# ADR-029: AI Agent Testing & Verification Philosophy

## Status

Accepted

## Date

2025-12-18

## Context

### The Problem: Tests That Lie

We discovered that many "E2E tests" for AI agents pass while the actual functionality is broken:

```python
# ACTUAL CODE FOUND IN CODEBASE (scripts/e2e_agentic_workflow_test.py:242-244)
def test_github_app_works(self):
    """Verify GitHub App can create files."""
    assert True  # ← Tests NOTHING
```

This represents a class of anti-patterns where:
1. Tests verify the agent's **claims** rather than **reality**
2. Success is measured by "no crash" rather than "correct outcome"
3. AI output is trusted without independent verification

### Why Traditional Testing Fails for AI Agents

| Traditional Code | AI Agent Code |
|------------------|---------------|
| Deterministic | Non-deterministic |
| Output is predictable | Output varies per run |
| Can test exact values | Must test properties |
| Trust function returns | Must verify world state |

### Root Cause Analysis

1. **Verification Gap**: We test that code ran, not that it achieved the goal
2. **Trust Model Mismatch**: We trust agent claims like we trust function returns
3. **Temporal Disconnect**: E2E tests run once; agents need continuous verification
4. **Evidence Poverty**: Agent actions don't produce verifiable evidence

## Decision

### Core Philosophy

> **"Don't trust the agent, verify the world."**

AI agents are non-deterministic. Their claims are testimony, not evidence. Always verify external state independently.

### The 5 Verification Levels

| Level | Name | Description | Example | Confidence |
|-------|------|-------------|---------|------------|
| 5 | **Invariant** | Property ALWAYS true | File hash matches claimed | ⭐⭐⭐⭐⭐ |
| 4 | **Outcome** | World state changed | PR exists in GitHub | ⭐⭐⭐⭐ |
| 3 | **Event** | Correct events emitted | PhaseCompleted in store | ⭐⭐⭐ |
| 2 | **Output** | Success status returned | `result.status == "completed"` | ⭐⭐ |
| 1 | **Existence** | Code didn't crash | `assert True` | ⭐ |

**Minimum acceptable level: 3 (Event Verification)**

**Target level for critical paths: 4-5 (Outcome/Invariant)**

### Principle 1: Verify the World, Not the Agent

Never trust agent claims. Always verify external state.

```python
# BAD: Trust agent's claim (Level 2)
result = agent.run("create file.py")
assert result.status == "success"  # Agent could be lying

# GOOD: Verify reality (Level 4)
result = agent.run("create file.py")
assert Path("file.py").exists()  # Check filesystem
content = Path("file.py").read_text()
compile(content, "file.py", "exec")  # Verify syntax
```

### Principle 2: Test Invariants, Not Exact Output

AI output is non-deterministic. Test properties that must always hold.

```python
# BAD: Test exact output (fragile)
assert agent.summarize(text) == "The expected summary"

# GOOD: Test invariants (robust)
summary = agent.summarize(text)
assert len(summary) < len(text) / 2  # Must be shorter
assert isinstance(summary, str)  # Must be text
assert len(summary) > 10  # Must be substantial
```

### Principle 3: Three-Source Verification for Critical Claims

For critical operations, verify from three independent sources:

```python
async def verify_pr_created(execution_id: str, claimed_pr: int) -> bool:
    # Source 1: Our event store
    events = await event_store.read(f"execution-{execution_id}")
    pr_event = next((e for e in events if e.type == "PRCreated"), None)

    # Source 2: External API (GitHub)
    github_pr = await github.get_pr(claimed_pr)

    # Source 3: Ground truth (git)
    branch_exists = await git_branch_exists(f"aef/{execution_id}")

    # All three must agree
    return (
        pr_event is not None
        and pr_event.data["pr_number"] == claimed_pr
        and github_pr is not None
        and branch_exists
    )
```

### Principle 4: Evidence-Based Actions

Every agent action must produce verifiable evidence:

```python
@dataclass
class VerifiableAction:
    action_type: str
    claimed_outcome: str

    # Evidence (not claims)
    file_hashes: dict[str, str]      # path → sha256
    api_response_ids: list[str]      # external system IDs
    event_ids: list[str]             # event store IDs
    timestamps: dict[str, datetime]  # operation timestamps

    async def verify(self) -> VerificationResult:
        """Every action can verify itself."""
        errors = []

        for path, expected_hash in self.file_hashes.items():
            if not Path(path).exists():
                errors.append(f"File {path} does not exist")
            elif hash_file(path) != expected_hash:
                errors.append(f"File {path} hash mismatch")

        return VerificationResult(
            success=len(errors) == 0,
            errors=errors,
        )
```

### Principle 5: Continuous Verification (Observability as Testing)

Build verification into the observability layer:

```python
class ContinuousVerifier:
    """Real-time verification of agent claims."""

    async def on_event(self, event: DomainEvent) -> None:
        verifier = VERIFIERS.get(event.type)
        if verifier:
            result = await verifier.verify(event)
            if not result.success:
                await self.emit_violation(event, result)
```

## Implementation

### 1. Verification Registry

Central registry of verifiers for each claim type:

```python
# packages/aef-shared/src/aef_shared/verification/registry.py
VERIFIERS: dict[str, Verifier] = {
    "file_created": FileExistsVerifier(),
    "pr_opened": GitHubPRVerifier(),
    "command_executed": CommandOutputVerifier(),
    "tests_passed": TestResultVerifier(),
}
```

### 2. Pytest Marker

```python
@pytest.mark.verification_level(4)  # Requires outcome verification
async def test_agent_creates_pr():
    ...
```

### 3. CI Enforcement

```yaml
# Fail if tests use Level 1-2 verification
- name: Check verification levels
  run: |
    if grep -r "assert True" tests/; then
      echo "❌ Found 'assert True' - Level 1 tests not allowed"
      exit 1
    fi
```

## Consequences

### Positive

- Eliminates "tests that lie"
- Catches agent failures that claimed success
- Enables continuous production verification
- Creates clear evidence trail for debugging
- Provides confidence for refactoring

### Negative

- More complex test setup
- External system dependencies for verification
- Slower tests (must check reality)
- More infrastructure for verification layer

### Mitigations

- Cache verification results
- Run Level 4+ tests only in CI (not on every save)
- Use testcontainers for external systems
- Async verification for non-blocking operations

## Compliance Checklist

When writing agent tests:

- [ ] No `assert True` or `assert result.success` without verification
- [ ] Every claim has evidence (file hash, API ID, event ID)
- [ ] Critical paths use 3-source verification
- [ ] Verification level >= 3 for all tests
- [ ] Tests can be re-run as health checks

## Related ADRs

- ADR-008: Test-Driven Development
- ADR-013: Integration Testing Strategy
- ADR-020: Event-Projection Consistency
- ADR-015: Agent Observability

## References

- [Property-Based Testing with Hypothesis](https://hypothesis.readthedocs.io/)
- [Contract Testing with Pact](https://docs.pact.io/)
- [Observability-Driven Development](https://www.honeycomb.io/observability-driven-development)

## Appendix: The Testing Pyramid for AI Systems

Traditional pyramid doesn't work for AI. Here's the adapted version:

```
                        ╱╲
                       ╱  ╲
                      ╱    ╲
                     ╱ LIVE ╲         ← Continuous verification
                    ╱ VERIFY ╲           in production (observability)
                   ╱──────────╲
                  ╱  CONTRACT  ╲       ← Does output satisfy invariants?
                 ╱    TESTS     ╲         (property-based testing)
                ╱────────────────╲
               ╱   INTEGRATION    ╲    ← Do components work together?
              ╱      TESTS         ╲      (with real infra)
             ╱──────────────────────╲
            ╱     UNIT TESTS         ╲ ← Does parsing/logic work?
           ╱     (deterministic)      ╲   (mock AI, test mechanics)
          ╱────────────────────────────╲
         ╱      SCHEMA VALIDATION       ╲ ← Is input/output well-formed?
        ╱────────────────────────────────╲
```

## Files Changed

- `docs/adrs/ADR-029-ai-agent-testing-verification.md` - This ADR
- `lib/agentic-primitives/primitives/v1/skills/testing/testing-expert/` - Testing expert skill
- `PROJECT-PLAN_20251218_TESTING-PHILOSOPHY.md` - Implementation plan
