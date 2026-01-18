# VSA Bug Report: execute_command Handler Not Detected

**Status:** CONFIRMED BUG
**Severity:** Medium
**Component:** `vsa-core/src/scanners/feature_scanner.rs`
**VSA Version:** (from event-sourcing-platform submodule)

## 🐛 Summary

VSA validation fails to detect `ExecuteCommandHandler.py` in the `execute_command` feature directory, despite the file existing, being correctly named, and matching all VSA patterns.

## 📝 Evidence

### ✅ What Works
- All other handlers in the `workspaces` context are detected correctly:
  - `create_workspace/CreateWorkspaceHandler.py` ✅
  - `destroy_workspace/DestroyWorkspaceHandler.py` ✅
  - `terminate_workspace/TerminateWorkspaceHandler.py` ✅
  - `inject_tokens/InjectTokensHandler.py` ✅
- The file exists and is readable:
  ```bash
  $ ls -la packages/aef-domain/src/aef_domain/contexts/workspaces/execute_command/
  -rw-r--r--@ 1 neural  staff   960 Jan 17 16:35 ExecuteCommandHandler.py
  ```
- Python can import it successfully
- The handler is correctly exported in `__init__.py`:
  ```python
  from aef_domain.contexts.workspaces.execute_command.ExecuteCommandHandler import (
      ExecuteCommandHandler,
  )
  __all__ = ["...", "ExecuteCommandHandler"]
  ```
- Pattern matching should work: `ExecuteCommandHandler` matches `*Handler` pattern

### ❌ What Fails
VSA validation consistently reports:
```
! Feature 'execute_command' in context 'workspaces' has a command but no handler
  at: ./packages/aef-domain/src/aef_domain/contexts/workspaces/execute_command
```

### 🧪 Tests Performed

1. **File Recreation Test:**
   - Deleted and recreated `ExecuteCommandHandler.py` → Still not detected

2. **New File Test:**
   - Created `ExecuteCommandHandler2.py` (copy of working handler) → Not detected
   - This proves the issue is **directory-specific**, not file-specific

3. **Permissions Test:**
   ```bash
   $ stat -f "%Sp" execute_command/ create_workspace/
   drwxr-xr-x  # Both identical
   ```

4. **gitignore Test:**
   - VSA uses `fs::read_dir` which bypasses gitignore
   - Python filesystem operations see the file correctly

5. **Extended Attributes Test:**
   ```bash
   $ xattr ExecuteCommandHandler.py
   com.apple.provenance  # Standard macOS attribute, same as working files
   ```

## 🔍 Investigation

### VSA Scanner Logic
From `lib/event-sourcing-platform/vsa/vsa-core/src/scanners/`:

```rust
// slice_scanner.rs
fn scan_slice_files(&self, slice_path: &Path) -> Result<Vec<SliceFile>> {
    for entry in fs::read_dir(slice_path)? {
        let path = entry.path();
        if path.is_file() {
            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                let file_type = self.classify_file(name);
                files.push(SliceFile { name: name.to_string(), path, file_type });
            }
        }
    }
}
```

This should work! The scanner:
1. Reads all files in the directory ✅
2. Classifies them by name pattern ✅
3. Should detect `ExecuteCommandHandler.py` ✅

### Hypothesis: Directory Scanning Anomaly

The bug appears to be **specific to the `execute_command` directory**. Possible causes:

1. **Directory Name Caching:** VSA might be caching directory contents and not refreshing
2. **Unicode/Encoding Issue:** Some invisible character in the directory name
3. **Race Condition:** Directory being scanned before file writes are fully committed
4. **Hidden File System Flag:** Some macOS Spotlight or filesystem flag preventing enumeration

## 🔬 Reproducible Test Case

```bash
# From project root
cd /path/to/agentic-engineering-framework

# Verify file exists
ls -la packages/aef-domain/src/aef_domain/contexts/workspaces/execute_command/ExecuteCommandHandler.py

# Run VSA validation
vsa validate

# Expected: 0 warnings
# Actual: 1 warning (missing handler for execute_command)
```

## 🎯 Workaround

**None identified.** Even recreating the directory and all files does not resolve the issue.

## 🛠️ Suggested Fix

1. **Add Debug Logging:** In `vsa-core/src/scanners/slice_scanner.rs`, log all files discovered:
   ```rust
   for entry in fs::read_dir(slice_path)? {
       let path = entry.path();
       eprintln!("DEBUG: Found file {:?}", path);  // Add this
       // ... rest of logic
   }
   ```

2. **Check Directory Enumeration:** Verify `fs::read_dir` is returning all files for `execute_command/`

3. **Compare with Working Directory:** Diff the scanning logic for `execute_command` vs `create_workspace`

## 📊 Impact

- **User Impact:** Low - This is the only failing feature out of 22 validated
- **Development Impact:** Medium - Prevents achieving 100% VSA compliance
- **False Positive Rate:** This is the only known false positive in the codebase

## 🏷️ Labels

- `bug`
- `vsa-core`
- `scanner`
- `false-positive`

---

**Reported By:** Cursor AI Agent (Agentic Engineering Framework Team)
**Date:** 2026-01-18
**Environment:** macOS 25.1.0, VSA from event-sourcing-platform submodule
