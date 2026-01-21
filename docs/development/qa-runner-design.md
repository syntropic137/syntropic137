# QA Runner - Simple Tool Design

## Purpose

A lightweight CLI tool that provides **visibility and enforcement** for QA checks.

**Core value:** Trust through transparency and constraint enforcement.

## Design Principles

1. **Simple** - One config file, one binary, minimal dependencies
2. **Helpful** - Clear output, actionable feedback
3. **Maintainable** - <500 lines of Rust, easy to understand
4. **Enforcing** - Hard timeouts, Andon thresholds

## Configuration

Single file: `qa.toml` at repo root

```toml
# qa.toml - QA Check Definitions

[settings]
green_zone = "60s"    # Target: <1 minute
yellow_zone = "120s"  # Warning: 1-2 minutes
red_zone = "600s"     # Andon: >2 minutes
andon_signal = "600s" # Critical: 10 minutes

[[check]]
name = "lint"
description = "Code quality and style analysis"
rationale = "Catches bugs, enforces consistency, improves readability"
command = "uv run ruff check ."
timeout = "30s"
target = "5s"

[[check]]
name = "format"
description = "Code formatting validation"
rationale = "Consistent style reduces cognitive load and merge conflicts"
command = "uv run ruff format --check ."
timeout = "30s"
target = "5s"

[[check]]
name = "typecheck"
description = "Static type validation"
rationale = "Catches type errors before runtime, improves IDE support"
command = "uv run pyright"
timeout = "60s"
target = "10s"

[[check]]
name = "test"
description = "Unit and integration test suite"
rationale = "Ensures functionality, prevents regressions, documents behavior"
command = "uv run pytest --tb=short"
timeout = "300s"
target = "30s"

[[check]]
name = "dashboard-qa"
description = "Frontend linting and build validation"
rationale = "Ensures UI code quality and build stability"
command = "just dashboard-qa"
timeout = "120s"
target = "30s"

[[check]]
name = "test-debt"
description = "Check for test skips/xfails without issue references"
rationale = "Prevents accumulation of orphaned test debt"
command = "just test-debt"
timeout = "30s"
target = "5s"

[[check]]
name = "vsa-validate"
description = "Architecture compliance validation"
rationale = "Enforces bounded context boundaries and VSA principles"
command = "./lib/event-sourcing-platform/vsa/target/release/vsa validate"
timeout = "30s"
target = "5s"
```

## CLI Interface

### Commands

```bash
# Run all checks (default)
qa-runner

# List all checks with descriptions
qa-runner list

# Show status and thresholds
qa-runner status

# Run specific checks
qa-runner run lint test

# Explain a check
qa-runner explain lint
```

### Output Format

**Human-friendly (default):**
```
🔍 Running QA Checks...

✅ lint          4.2s  (target: 5s)   [Green]
   Code quality and style analysis

✅ format        2.8s  (target: 5s)   [Green]
   Code formatting validation

⚠️  typecheck    12.1s (target: 10s)  [Yellow - Slow]
   Static type validation
   Warning: 2.1s over target

✅ test_debt     1.9s  (target: 5s)   [Green]
   Check for test skips without issues

✅ vsa_validate  4.7s  (target: 5s)   [Green]
   Architecture compliance validation

⚠️  test         89.2s (target: 30s)  [Yellow - Slow]
   Unit and integration test suite
   Warning: 59.2s over target

✅ dashboard_qa  28.3s (target: 30s)  [Green]
   Frontend linting and build

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️  Total: 142.1s (2.4min)
🟡 Status: YELLOW ZONE

📊 Performance:
   Target:  <60s  (Green)
   Current: 142s  (Yellow)
   Delta:   +82s over target

💡 Recommendations:
   1. Optimize 'test' - 59s over target
   2. Optimize 'typecheck' - 2s over target

🎯 Next milestone: Get to <120s (yellow threshold)
```

**AI-friendly (--json):**
```json
{
  "status": "yellow",
  "duration_seconds": 142.1,
  "thresholds": {
    "green": 60,
    "yellow": 120,
    "red": 600
  },
  "checks": [
    {
      "name": "lint",
      "description": "Code quality and style analysis",
      "passed": true,
      "duration": 4.2,
      "target": 5.0,
      "status": "green"
    },
    {
      "name": "test",
      "description": "Unit and integration test suite",
      "passed": true,
      "duration": 89.2,
      "target": 30.0,
      "status": "yellow",
      "over_target_by": 59.2
    }
  ],
  "recommendations": [
    "Optimize 'test' - 59s over target",
    "Optimize 'typecheck' - 2s over target"
  ]
}
```

### Command: `qa-runner list`

```
📋 QA Checks (7 configured)

1. lint (target: 5s)
   Code quality and style analysis
   Rationale: Catches bugs, enforces consistency, improves readability

2. format (target: 5s)
   Code formatting validation
   Rationale: Consistent style reduces cognitive load

3. typecheck (target: 10s)
   Static type validation
   Rationale: Catches type errors before runtime

4. test (target: 30s)
   Unit and integration test suite
   Rationale: Ensures functionality, prevents regressions

5. dashboard-qa (target: 30s)
   Frontend linting and build validation
   Rationale: Ensures UI code quality

6. test-debt (target: 5s)
   Check for test skips without issue references
   Rationale: Prevents accumulation of orphaned debt

7. vsa-validate (target: 5s)
   Architecture compliance validation
   Rationale: Enforces bounded context boundaries
```

### Command: `qa-runner explain lint`

```
🔍 Check: lint

Description:
  Code quality and style analysis

Rationale:
  Catches bugs, enforces consistency, improves readability

Command:
  uv run ruff check .

Performance:
  Target:  5s
  Timeout: 30s

What it validates:
  • Unused imports
  • Undefined names
  • Code complexity
  • Style consistency
  • Import sorting

Why it matters:
  Quality issues caught early are 10x cheaper to fix than
  in production. Consistent style reduces code review time
  by 30% and merge conflicts by 50%.
```

## Implementation

### File Structure

```
qa-runner/
├── Cargo.toml           # Minimal dependencies (clap, serde, toml)
├── src/
│   ├── main.rs          # CLI + command routing (~100 lines)
│   ├── config.rs        # Load/parse qa.toml (~50 lines)
│   ├── executor.rs      # Run checks, measure time (~100 lines)
│   ├── display.rs       # Human-friendly output (~100 lines)
│   └── andon.rs         # Threshold checking (~50 lines)
└── tests/
    └── integration.rs   # Basic tests (~100 lines)

Total: ~500 lines
```

### Dependencies (Minimal)

```toml
[dependencies]
clap = "4.0"           # CLI parsing
serde = "1.0"          # Serialization
toml = "0.8"           # Config parsing
colored = "2.0"        # Terminal colors
serde_json = "1.0"     # JSON output
```

### Core Logic

```rust
// src/executor.rs (simplified)

pub fn run_check(check: &Check) -> CheckResult {
    let start = Instant::now();

    let output = Command::new("sh")
        .arg("-c")
        .arg(&check.command)
        .timeout(check.timeout)
        .output()?;

    let duration = start.elapsed();
    let passed = output.status.success();

    let status = if !passed {
        Status::Failed
    } else if duration > check.target * 2 {
        Status::Red  // Way over target
    } else if duration > check.target {
        Status::Yellow  // Over target
    } else {
        Status::Green  // At target
    };

    CheckResult {
        name: check.name,
        passed,
        duration,
        target: check.target,
        status,
    }
}

pub fn run_all_checks(checks: &[Check]) -> Summary {
    let results: Vec<CheckResult> = checks
        .iter()
        .map(|check| run_check(check))
        .collect();

    let total_duration: Duration = results
        .iter()
        .map(|r| r.duration)
        .sum();

    let overall_status = determine_status(total_duration, &thresholds);

    Summary {
        results,
        total_duration,
        status: overall_status,
    }
}
```

## Integration

### Update justfile

```just
# Run QA checks using qa-runner
qa:
    qa-runner

# List all QA checks
qa-list:
    qa-runner list

# Check QA status
qa-status:
    qa-runner status
```

### CI Integration

```yaml
# .github/workflows/qa.yml
- name: Run QA Checks
  run: |
    qa-runner --json > qa-results.json

- name: Check Andon Status
  run: |
    status=$(jq -r '.status' qa-results.json)
    if [ "$status" = "red" ]; then
      echo "🚨 RED ZONE - Performance degraded"
      exit 1
    fi
```

## Migration Plan

1. **Phase 1:** Build `qa-runner` MVP
   - Parse qa.toml
   - Run checks sequentially
   - Display results
   - Enforce timeouts

2. **Phase 2:** Replace `just qa`
   - Create qa.toml with all checks
   - Update justfile to use qa-runner
   - Test in CI

3. **Phase 3:** Add intelligence
   - Performance tracking over time
   - Better recommendations
   - Historical trends

## Why This Works

**Simple:**
- One config file
- One binary
- No database, no server
- <500 lines of code

**Helpful:**
- Clear descriptions
- Explains why each check matters
- Actionable recommendations
- Human AND machine readable

**Maintainable:**
- Pure Rust, no external services
- Easy to understand
- Well-tested
- Integrates with existing tools

**Enforcing:**
- Hard timeouts prevent hangs
- Andon thresholds catch regressions
- Exit codes signal failure
- JSON output for automation

## Success Criteria

1. ✅ Adds value from day 1 (better visibility)
2. ✅ Easy to add new checks (just edit qa.toml)
3. ✅ Clear feedback (humans understand output)
4. ✅ Automation friendly (machines can parse JSON)
5. ✅ Maintainable (anyone can fix/improve)
6. ✅ Enforces constraints (timeouts, Andon)
