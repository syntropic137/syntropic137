# CI Self-Healing

Automatically diagnose and fix CI failures on pull requests

## Usage

```bash
syn workflow install .
syn workflow run dc5678c9-6289-484f-8e53-61f2165fa700 --task "Your task here"
```

## Phases

- **Phase 1:** Diagnose Failure
- **Phase 2:** Apply Fix
- **Phase 3:** Verify Fix
