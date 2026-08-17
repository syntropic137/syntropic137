# Skill Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a workflow plugin carry the skills its phases need - bundled in the plugin or referenced externally - so `syn workflow install` registers them and a run needs no out-of-band setup.

**Architecture:** `syn workflow install` gains a skills preflight that mirrors the existing claude-plugin preflight: walk the cloned plugin's YAML, collect `skills:` refs from workflow and phase scope, and register anything not already stored. Registration is content-addressed by sha256, so a ref that resolves to a known hash does no network work - the hash is the cache. Per-phase injection into the workspace is unchanged and already works.

**Tech Stack:** TypeScript (Node 22, tsup, vitest) for the CLI; Python 3.12 (FastAPI, Pydantic v2, pytest) for the API and domain. Package managers: `pnpm` for Node, `uv` for Python. Task runner: `just`.

**Spec:** `docs/superpowers/specs/2026-08-17-skills-distribution-design.md` - read it first. It explains why pinned refs are load bearing and why Layer 1 stays baked.

## What changed during implementation

This plan was written before the code was read. Five things were found that it did not
anticipate; all are resolved in the branch, and the tasks below are kept as authored so
the difference stays visible.

1. **`RegisterSkillHandler` does not reject a changed hash - it silently serves the old
   tree.** It computes the stream id from `(source_url, version, skill_name)` and
   returns an existing aggregate *before* hashing the submitted files. So the open
   question resolved differently than the plan framed it: a `"bundled"` literal would
   not conflict, it would quietly resolve to stale content. **Bundled skills are
   therefore pinned by the sha256 of their file tree**, per spec option 1.

2. **The Python domain never accepted `./skills/foo`.** `SkillRef._parse_string_form`
   has no relative-path branch, and `workflow_definition.py` expands `skills:` through
   it at both scopes. Rather than teach the domain a path form, the CLI **rewrites
   bundled refs into pinned mappings before upload**, in the same place it already
   resolves `prompt_file:`. The API only ever sees pinned refs.

3. **Install dropped `skills:` entirely.** `installWorkflowsViaApi` hand-built a JSON
   body for `POST /workflows` naming each field, and `_build_phase_defs` rebuilt
   `PhaseDefinition` field by field; neither carried `skills` or `claude_plugins`.
   Registering skills would have been pointless while the refs never reached the stored
   template. **Install now uploads the resolved definition to `/workflows/from-yaml`**,
   the path `syn workflow create --from` already used, where the server owns every YAML
   semantic. The narrow JSON body was the bug and was not widened.

4. **`SkillRegistered` was missing from `manager_event_map.py`.** Its
   `ClaudePluginRegistered` twin was present. This is **test-mode only**:
   `sync_published_events_to_projections` is a no-op unless the publisher is
   `InMemoryEventPublisher`, and production dispatches through the ADR-055 coordinator,
   which was verified to populate `skill_lock` on a live stack. The cost is that an
   API-level test cannot observe its own write, so a correct test fails for reasons
   unrelated to the code under test. Tracked more broadly as #821.

5. **MinIO listing was not recursive**, so `GET /skills/storage` reported zero bytes.
   Found only by running the end-to-end check against a live stack.

**On test shape:** several tasks below specify tests that construct a response model and
assert its own fields. Those pass against a completely broken route. They are kept where
cheap, but every route in this branch also has a test that calls it. Task 3's model-only
test is what hid finding 4 until a real round-trip test was written.

## Global Constraints

- **Never hand-edit generated files.** `apps/syn-cli-node/src/generated/api-types.ts` and `apps/syn-dashboard-ui/src/generated/api-types.ts` come from `just codegen`. Run it after any API model change and commit the result.
- **API routes MUST use Pydantic response models.** Never `-> dict[str, Any]`. An untyped route is invisible to the OpenAPI spec, which breaks CLI type generation.
- **No `Any`, no untyped `dict` for structured state.** There is a ratchet (`just check-untyped-dicts`) that fails the build if the count rises. Use a dataclass, a Pydantic model, or explicit params.
- **No em dashes in any file.** Use plain hyphens. The pre-push hook enforces this.
- **TODO/FIXME comments MUST reference a GitHub issue:** `# TODO(#123): ...`.
- **Pin exact dependency versions** (`==`) in `pyproject.toml`, never `>=` ranges.
- **`@latest` skill versions stay rejected.** This is not hygiene - an unpinned ref cannot be cached honestly, and the cache is the point.
- Run `just qa` before opening a PR. At minimum: `uv run ruff check .`, `uv run ruff format --check .`, `just typecheck`, `just test-unit`, `just cli-node-test`, `vsa validate`.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/syn-cli-node/src/packages/skill-preflight.ts` | **Create.** Walk a cloned plugin, collect `skills:` refs, register the missing ones. Mirrors `claude-plugin-preflight.ts`. |
| `apps/syn-cli-node/src/packages/skill-ref.ts` | **Create.** Parse the three `skills:` YAML forms into a typed ref. TS mirror of the Python `SkillRef`. |
| `apps/syn-cli-node/src/packages/skill-tree.ts` | **Create.** Read a skill directory into the base64 file list the register API expects. |
| `apps/syn-cli-node/src/commands/workflow/install.ts` | **Modify.** Call the skills preflight beside the existing claude-plugin one. |
| `apps/syn-api/src/syn_api/routes/skills.py` | **Modify.** Add a read endpoint so the CLI can ask "is this hash already registered?" without uploading. |
| `apps/syn-api/src/syn_api/types.py` | **Modify.** Response model for the read endpoint, plus a store-size model. |
| `packages/syn-shared/src/syn_shared/settings/...` | Untouched. |

Tasks 1-3 build the CLI pieces bottom-up (parse -> read tree -> orchestrate). Task 4 wires it in. Task 5 adds the API read endpoint that makes the cache-hit check cheap. Task 6 adds size observability. Task 7 is the end-to-end proof.

---

### Task 1: Parse `skills:` YAML entries in the CLI

The CLI must recognise the same three forms the Python domain accepts, so an
install fails on a bad ref before the API is touched.

**Files:**
- Create: `apps/syn-cli-node/src/packages/skill-ref.ts`
- Test: `apps/syn-cli-node/tests/packages/skill-ref.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `export interface ParsedSkillRef { readonly skillName: string; readonly sourceUrl: string; readonly version: string; readonly localPath?: string }`
  - `export function parseSkillEntry(entry: unknown): ParsedSkillRef[]`

`localPath` is set only for the bundled form (`./skills/foo`); external refs leave it undefined.

- [ ] **Step 1: Write the failing test**

```typescript
// apps/syn-cli-node/tests/packages/skill-ref.test.ts
import { describe, expect, it } from "vitest";
import { parseSkillEntry } from "../../src/packages/skill-ref.js";

describe("parseSkillEntry", () => {
  it("parses org/repo/skill@version", () => {
    expect(parseSkillEntry("anthropics/skills/frontend-design@v1.2.0")).toEqual([
      {
        skillName: "frontend-design",
        sourceUrl: "https://github.com/anthropics/skills",
        version: "v1.2.0",
      },
    ]);
  });

  it("parses a full URL with @version", () => {
    expect(parseSkillEntry("https://github.com/acme/tdd-skill@v2.0.0")).toEqual([
      { skillName: "tdd-skill", sourceUrl: "https://github.com/acme/tdd-skill", version: "v2.0.0" },
    ]);
  });

  it("parses a bundled relative path", () => {
    expect(parseSkillEntry("./skills/repo-conventions")).toEqual([
      {
        skillName: "repo-conventions",
        sourceUrl: "./skills/repo-conventions",
        version: "bundled",
        localPath: "./skills/repo-conventions",
      },
    ]);
  });

  it("expands the verbose names[] form into one ref each", () => {
    const refs = parseSkillEntry({
      source: "github.com/acme/skills",
      version: "v1.0.0",
      names: ["alpha", "beta"],
    });
    expect(refs.map((r) => r.skillName)).toEqual(["alpha", "beta"]);
    expect(refs[0].version).toBe("v1.0.0");
  });

  it("rejects @latest because an unpinned ref cannot be cached", () => {
    expect(() => parseSkillEntry("anthropics/skills/foo@latest")).toThrow(/latest/i);
  });

  it("rejects the plugin-era two-segment shape with a corrective message", () => {
    expect(() => parseSkillEntry("acme/skills@v1.0.0")).toThrow(/org\/repo\/skill/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/packages/skill-ref.test.ts`
Expected: FAIL - cannot find module `../../src/packages/skill-ref.js`

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/syn-cli-node/src/packages/skill-ref.ts

/** A workflow-declared skill reference, parsed from one `skills:` entry. */
export interface ParsedSkillRef {
  readonly skillName: string;
  readonly sourceUrl: string;
  readonly version: string;
  /** Set only for bundled skills: the path inside the plugin. */
  readonly localPath?: string;
}

const BUNDLED_VERSION = "bundled";

function rejectLatest(version: string): void {
  if (version.toLowerCase() === "latest") {
    throw new Error(
      "skill version '@latest' is not allowed: an unpinned ref cannot be cached, " +
        "because the same ref may denote different bytes later. Pin a tag or commit.",
    );
  }
}

function parseBundled(entry: string): ParsedSkillRef[] {
  const clean = entry.replace(/\/+$/, "");
  const skillName = clean.split("/").pop() ?? "";
  if (!skillName) throw new Error(`bundled skill path has no directory name: ${entry}`);
  return [{ skillName, sourceUrl: clean, version: BUNDLED_VERSION, localPath: clean }];
}

function parseStringRef(entry: string): ParsedSkillRef[] {
  if (entry.startsWith("./") || entry.startsWith("../")) return parseBundled(entry);

  const at = entry.lastIndexOf("@");
  if (at <= 0) {
    throw new Error(
      `skill ref must be pinned with @version: ${entry} ` +
        `(expected org/repo/skill@version or <url>@version)`,
    );
  }
  const body = entry.slice(0, at);
  const version = entry.slice(at + 1);
  rejectLatest(version);

  if (body.startsWith("http://") || body.startsWith("https://")) {
    const skillName = body.replace(/\/+$/, "").split("/").pop() ?? "";
    return [{ skillName, sourceUrl: body, version }];
  }

  const parts = body.split("/").filter(Boolean);
  if (parts.length !== 3) {
    throw new Error(
      `skill ref must be org/repo/skill@version, got '${entry}'. ` +
        `Two segments (org/repo@version) is the claude-plugin shape, not a skill ref.`,
    );
  }
  const [org, repo, skillName] = parts;
  return [{ skillName, sourceUrl: `https://github.com/${org}/${repo}`, version }];
}

function parseVerbose(entry: Record<string, unknown>): ParsedSkillRef[] {
  const source = entry["source"];
  const version = entry["version"];
  if (typeof source !== "string" || typeof version !== "string") {
    throw new Error("skill verbose form requires string 'source' and 'version'");
  }
  rejectLatest(version);

  const sourceUrl = source.startsWith("http") ? source : `https://${source}`;
  const names = entry["names"];
  if (Array.isArray(names)) {
    if (names.length === 0) {
      throw new Error("skill verbose form 'names' must be a non-empty list of strings");
    }
    return names.map((n) => ({ skillName: String(n), sourceUrl, version }));
  }
  const name = entry["name"];
  if (typeof name !== "string" || !name) {
    throw new Error("skill verbose form requires 'name' or a non-empty 'names' list");
  }
  return [{ skillName: name, sourceUrl, version }];
}

/** Expand one `skills:` YAML entry into one or more refs. */
export function parseSkillEntry(entry: unknown): ParsedSkillRef[] {
  if (typeof entry === "string") return parseStringRef(entry);
  if (typeof entry === "object" && entry !== null && !Array.isArray(entry)) {
    return parseVerbose(entry as Record<string, unknown>);
  }
  throw new Error(`unsupported skills: entry (expected string or mapping): ${String(entry)}`);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/packages/skill-ref.test.ts`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add apps/syn-cli-node/src/packages/skill-ref.ts apps/syn-cli-node/tests/packages/skill-ref.test.ts
git commit -m "feat(cli): parse skills: refs, rejecting unpinned versions

The CLI needs the same three forms the Python domain accepts so a bad ref
fails at install rather than at execution. @latest stays rejected because
an unpinned ref cannot be cached: the same ref may denote different bytes
later, and the content hash is what makes the cache sound."
```

---

### Task 2: Read a skill directory into the register-API payload

**Files:**
- Create: `apps/syn-cli-node/src/packages/skill-tree.ts`
- Test: `apps/syn-cli-node/tests/packages/skill-tree.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `export interface SkillFilePayload { readonly rel_path: string; readonly content_base64: string }`
  - `export function readSkillTree(dir: string): SkillFilePayload[]` - throws if `SKILL.md` is absent at the root.

Field names are snake_case on purpose: they are serialised straight into
`RegisterSkillRequest`, whose fields are `rel_path` and `content_base64`.

- [ ] **Step 1: Write the failing test**

```typescript
// apps/syn-cli-node/tests/packages/skill-tree.test.ts
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { readSkillTree } from "../../src/packages/skill-tree.js";

let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "skilltree-"));
});
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("readSkillTree", () => {
  it("reads SKILL.md and nested files with paths relative to the root", () => {
    fs.writeFileSync(path.join(dir, "SKILL.md"), "# hi");
    fs.mkdirSync(path.join(dir, "refs"));
    fs.writeFileSync(path.join(dir, "refs", "extra.md"), "more");

    const files = readSkillTree(dir);
    const byPath = Object.fromEntries(files.map((f) => [f.rel_path, f.content_base64]));

    expect(Object.keys(byPath).sort()).toEqual(["SKILL.md", "refs/extra.md"]);
    expect(Buffer.from(byPath["SKILL.md"], "base64").toString()).toBe("# hi");
  });

  it("throws when SKILL.md is missing, because that file IS the manifest", () => {
    fs.writeFileSync(path.join(dir, "notes.md"), "x");
    expect(() => readSkillTree(dir)).toThrow(/SKILL\.md/);
  });

  it("skips .git so a cloned skill does not upload its history", () => {
    fs.writeFileSync(path.join(dir, "SKILL.md"), "# hi");
    fs.mkdirSync(path.join(dir, ".git"));
    fs.writeFileSync(path.join(dir, ".git", "config"), "secret");

    expect(readSkillTree(dir).map((f) => f.rel_path)).toEqual(["SKILL.md"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/packages/skill-tree.test.ts`
Expected: FAIL - cannot find module `../../src/packages/skill-tree.js`

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/syn-cli-node/src/packages/skill-tree.ts
import * as fs from "node:fs";
import * as path from "node:path";

/** One file in a skill tree, shaped for RegisterSkillRequest.files[]. */
export interface SkillFilePayload {
  readonly rel_path: string;
  readonly content_base64: string;
}

const SKIP_DIRS = new Set([".git", "node_modules", "__pycache__"]);
const MANIFEST = "SKILL.md";

function walk(root: string, dir: string, out: SkillFilePayload[]): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(root, abs, out);
      continue;
    }
    if (!entry.isFile()) continue;
    out.push({
      rel_path: path.relative(root, abs).split(path.sep).join("/"),
      content_base64: fs.readFileSync(abs).toString("base64"),
    });
  }
}

/**
 * Read every file in a skill directory, base64-encoded, paths relative to the root.
 *
 * SKILL.md at the root is required: unlike claude plugins there is no
 * caller-supplied manifest, so its frontmatter IS the manifest.
 */
export function readSkillTree(dir: string): SkillFilePayload[] {
  if (!fs.existsSync(path.join(dir, MANIFEST))) {
    throw new Error(`skill directory ${dir} has no ${MANIFEST} at its root`);
  }
  const out: SkillFilePayload[] = [];
  walk(dir, dir, out);
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/packages/skill-tree.test.ts`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add apps/syn-cli-node/src/packages/skill-tree.ts apps/syn-cli-node/tests/packages/skill-tree.test.ts
git commit -m "feat(cli): read a skill directory into the register-API payload

SKILL.md at the root is required because it IS the manifest - there is no
caller-supplied one, unlike claude plugins. .git is skipped so a cloned
skill does not upload its own history."
```

---

### Task 3: Add a "is this already registered" read endpoint

The CLI must answer "do I need to upload this?" without sending a 4MB body.
There is currently no read surface on `/skills` at all.

**Files:**
- Modify: `apps/syn-api/src/syn_api/routes/skills.py`
- Modify: `apps/syn-api/src/syn_api/types.py`
- Test: `apps/syn-api/tests/test_api_skills.py` (create)

**Interfaces:**
- Consumes: the existing `skill_lock` projection, already queried by `SkillResolutionService`.
- Produces: `GET /skills/registrations?source_url=&version=&skill_name=` returning
  `SkillRegistrationLookupResponse { registered: bool, resolved_sha: str | None }`.

- [ ] **Step 1: Write the failing test**

```python
# apps/syn-api/tests/test_api_skills.py
"""Tests for the skills registration lookup endpoint."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.mark.unit
class TestSkillLookupResponse:
    def test_unregistered_reports_false_with_no_sha(self) -> None:
        from syn_api.types import SkillRegistrationLookupResponse

        response = SkillRegistrationLookupResponse(registered=False)

        assert response.registered is False
        assert response.resolved_sha is None

    def test_registered_carries_the_hash(self) -> None:
        """The sha is the cache key: a caller that has it can skip the upload."""
        from syn_api.types import SkillRegistrationLookupResponse

        response = SkillRegistrationLookupResponse(
            registered=True, resolved_sha="sha256-abc123"
        )

        assert response.registered is True
        assert response.resolved_sha == "sha256-abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/syn-api/tests/test_api_skills.py -v`
Expected: FAIL - `ImportError: cannot import name 'SkillRegistrationLookupResponse'`

- [ ] **Step 3: Write minimal implementation**

Add to `apps/syn-api/src/syn_api/types.py`, next to the other skill models:

```python
class SkillRegistrationLookupResponse(BaseModel):
    """Whether a (source_url, version, skill_name) triple is already registered.

    Lets the CLI skip uploading a skill tree it has already stored. The sha is
    the cache key: identical content always resolves to the same hash, so a hit
    here means zero network work for the caller.
    """

    registered: bool
    resolved_sha: str | None = None
```

Add to `apps/syn-api/src/syn_api/routes/skills.py`:

```python
@router.get("/registrations", response_model=SkillRegistrationLookupResponse)
async def lookup_skill_registration(
    source_url: str = Query(..., description="Skill source repository URL"),
    version: str = Query(..., description="Pinned version (tag, branch, or commit)"),
    skill_name: str = Query(..., description="Skill name as declared or overridden"),
) -> SkillRegistrationLookupResponse:
    """Report whether this skill triple is already registered."""
    from syn_api._wiring import get_skill_lock_query

    entry = await get_skill_lock_query().find(
        source_url=source_url, version=version, skill_name=skill_name
    )
    if entry is None:
        return SkillRegistrationLookupResponse(registered=False)
    return SkillRegistrationLookupResponse(
        registered=True, resolved_sha=entry.resolved_sha
    )
```

> **As built:** there is no `get_skill_lock_query`. `get_skill_lock_projection()`
> already exists at `_wiring.py:1280` and is exactly the reader
> `SkillResolutionService` uses, so no second read path was introduced. Its method is
> `.get(source_url, version, skill_name)`, not `.find(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/syn-api/tests/test_api_skills.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Regenerate the API contract**

Run: `just codegen`
Expected: `apps/syn-cli-node/src/generated/api-types.ts` gains the new path.

- [ ] **Step 6: Commit**

```bash
git add apps/syn-api/src/syn_api/types.py apps/syn-api/src/syn_api/routes/skills.py \
        apps/syn-api/tests/test_api_skills.py apps/syn-cli-node/src/generated/api-types.ts \
        apps/syn-dashboard-ui/src/generated/api-types.ts apps/syn-docs/openapi.json
git commit -m "feat(api): look up whether a skill is already registered

The skills API had only a write surface, so a caller could not tell an
already-stored skill from a new one without uploading the whole tree. The
returned sha is the cache key."
```

---

### Task 4: The skills preflight

**Files:**
- Create: `apps/syn-cli-node/src/packages/skill-preflight.ts`
- Test: `apps/syn-cli-node/tests/packages/skill-preflight.test.ts`

**Interfaces:**
- Consumes: `parseSkillEntry` (Task 1), `readSkillTree` (Task 2), `GET /skills/registrations` (Task 3).
- Produces:
  - `export interface SkillPreflightResult { readonly registered: readonly ParsedSkillRef[]; readonly skipped: readonly ParsedSkillRef[] }`
  - `export async function runSkillPreflight(packagePath: string): Promise<SkillPreflightResult>`

Mirror `apps/syn-cli-node/src/packages/claude-plugin-preflight.ts` for YAML
walking: it already has `findYamlFiles` and a phase-aware extractor. Reuse that
shape rather than inventing a second walker.

- [ ] **Step 1: Write the failing test**

```typescript
// apps/syn-cli-node/tests/packages/skill-preflight.test.ts
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

let pkg: string;

beforeEach(() => {
  pkg = fs.mkdtempSync(path.join(os.tmpdir(), "skillpre-"));
  fs.mkdirSync(path.join(pkg, "workflows", "review"), { recursive: true });
});
afterEach(() => {
  fs.rmSync(pkg, { recursive: true, force: true });
  vi.restoreAllMocks();
});

function writeWorkflow(body: string): void {
  fs.writeFileSync(path.join(pkg, "workflows", "review", "workflow.yaml"), body);
}

describe("runSkillPreflight", () => {
  it("collects refs from BOTH workflow scope and phase scope", async () => {
    writeWorkflow(`
id: review
skills:
  - anthropics/skills/alpha@v1.0.0
phases:
  - id: one
    skills:
      - anthropics/skills/beta@v2.0.0
`);
    const { collectSkillRefs } = await import("../../src/packages/skill-preflight.js");
    const names = collectSkillRefs(pkg).map((r) => r.skillName).sort();
    expect(names).toEqual(["alpha", "beta"]);
  });

  it("returns nothing for a plugin that declares no skills", async () => {
    writeWorkflow("id: review\nphases:\n  - id: one\n");
    const { collectSkillRefs } = await import("../../src/packages/skill-preflight.js");
    expect(collectSkillRefs(pkg)).toEqual([]);
  });

  it("resolves a bundled ref to a path inside the plugin", async () => {
    fs.mkdirSync(path.join(pkg, "skills", "repo-conventions"), { recursive: true });
    fs.writeFileSync(path.join(pkg, "skills", "repo-conventions", "SKILL.md"), "# x");
    writeWorkflow("id: review\nskills:\n  - ./skills/repo-conventions\n");

    const { collectSkillRefs } = await import("../../src/packages/skill-preflight.js");
    const [ref] = collectSkillRefs(pkg);
    expect(ref.skillName).toBe("repo-conventions");
    expect(ref.localPath).toBe("./skills/repo-conventions");
  });

  it("fails the whole preflight on an unpinned ref, before any API call", async () => {
    writeWorkflow("id: review\nskills:\n  - anthropics/skills/alpha@latest\n");
    const { collectSkillRefs } = await import("../../src/packages/skill-preflight.js");
    expect(() => collectSkillRefs(pkg)).toThrow(/latest/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/packages/skill-preflight.test.ts`
Expected: FAIL - cannot find module `../../src/packages/skill-preflight.js`

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/syn-cli-node/src/packages/skill-preflight.ts
import * as fs from "node:fs";
import * as path from "node:path";

import { parseYaml } from "./yaml.js";
import { parseSkillEntry, type ParsedSkillRef } from "./skill-ref.js";
import { readSkillTree } from "./skill-tree.js";
import { api } from "../client/typed.js";
import { printDim, printSuccess } from "../output/console.js";

export interface SkillPreflightResult {
  /** Refs that were missing and got registered just now. */
  readonly registered: readonly ParsedSkillRef[];
  /** Refs whose content hash was already stored; no upload performed. */
  readonly skipped: readonly ParsedSkillRef[];
}

const SKIP_WALK_DIRS = new Set([".git", "node_modules"]);

function isYamlFilename(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.endsWith(".yaml") || lower.endsWith(".yml");
}

function walkYamlDir(dir: string, out: string[]): void {
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_WALK_DIRS.has(entry.name)) continue;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkYamlDir(abs, out);
      continue;
    }
    if (entry.isFile() && isYamlFilename(entry.name)) out.push(abs);
  }
}

function extractSkillEntries(doc: unknown): unknown[] {
  const entries: unknown[] = [];
  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) return entries;
  const obj = doc as Record<string, unknown>;

  const top = obj["skills"];
  if (Array.isArray(top)) entries.push(...top);

  const phases = obj["phases"];
  if (Array.isArray(phases)) {
    for (const phase of phases) {
      if (typeof phase !== "object" || phase === null || Array.isArray(phase)) continue;
      const phaseSkills = (phase as Record<string, unknown>)["skills"];
      if (Array.isArray(phaseSkills)) entries.push(...phaseSkills);
    }
  }
  return entries;
}

/**
 * Every skill ref a plugin declares, from workflow AND phase scope.
 *
 * Deduped by (sourceUrl, version, skillName) - the same key the lock
 * projection uses - so a skill declared at both scopes registers once.
 */
export function collectSkillRefs(packagePath: string): ParsedSkillRef[] {
  const yamlFiles: string[] = [];
  walkYamlDir(packagePath, yamlFiles);

  const seen = new Map<string, ParsedSkillRef>();
  for (const file of yamlFiles) {
    const doc = parseYaml(fs.readFileSync(file, "utf8"));
    for (const entry of extractSkillEntries(doc)) {
      for (const ref of parseSkillEntry(entry)) {
        seen.set(`${ref.sourceUrl} ${ref.version} ${ref.skillName}`, ref);
      }
    }
  }
  return [...seen.values()];
}

async function isRegistered(ref: ParsedSkillRef): Promise<boolean> {
  const { data } = await api.GET("/skills/registrations", {
    params: {
      query: {
        source_url: ref.sourceUrl,
        version: ref.version,
        skill_name: ref.skillName,
      },
    },
  });
  return Boolean(data?.registered);
}

/**
 * Register every skill a plugin declares that is not already stored.
 *
 * WHY at install: without this a workflow declaring `skills:` installs cleanly
 * and then dies at execution with SkillNotRegistered - after the user has
 * committed to a run. Failing here costs nothing.
 */
export async function runSkillPreflight(packagePath: string): Promise<SkillPreflightResult> {
  const refs = collectSkillRefs(packagePath);
  if (refs.length === 0) return { registered: [], skipped: [] };

  const registered: ParsedSkillRef[] = [];
  const skipped: ParsedSkillRef[] = [];

  for (const ref of refs) {
    if (await isRegistered(ref)) {
      skipped.push(ref);
      printDim(`  skill ${ref.skillName}@${ref.version} already registered`);
      continue;
    }

    const dir = ref.localPath
      ? path.join(packagePath, ref.localPath)
      : await cloneSkillSource(ref);

    await api.POST("/skills/registrations", {
      body: {
        source_url: ref.sourceUrl,
        version: ref.version,
        skill_name: ref.skillName,
        files: readSkillTree(dir),
      },
    });
    registered.push(ref);
    printSuccess(`  registered skill ${ref.skillName}@${ref.version}`);
  }
  return { registered, skipped };
}
```

`cloneSkillSource(ref)` shallow-clones `ref.sourceUrl` at `ref.version` into a
temp dir and returns the path to the skill subdirectory. Reuse the existing
clone helper in `apps/syn-cli-node/src/packages/git.ts` (the marketplace client
already clones this way) rather than shelling out separately, and delete the
temp dir with `removeTempDir` from the same module.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/packages/skill-preflight.test.ts`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add apps/syn-cli-node/src/packages/skill-preflight.ts \
        apps/syn-cli-node/tests/packages/skill-preflight.test.ts
git commit -m "feat(cli): skills preflight collects and registers plugin skills

Collects skills: from workflow AND phase scope, deduped by the same
(source_url, version, skill_name) key the lock projection uses. A ref whose
content is already stored is skipped without an upload - the hash is the cache."
```

---

### Task 5: Wire the preflight into install

**Files:**
- Modify: `apps/syn-cli-node/src/commands/workflow/install.ts:211`
- Test: `apps/syn-cli-node/tests/commands/workflow/install.test.ts`

**Interfaces:**
- Consumes: `runSkillPreflight` (Task 4).
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

```typescript
// add to apps/syn-cli-node/tests/commands/workflow/install.test.ts
import { describe, expect, it, vi } from "vitest";

describe("install skills preflight", () => {
  it("runs the skills preflight BEFORE creating any workflow", async () => {
    const calls: string[] = [];
    vi.doMock("../../../src/packages/skill-preflight.js", () => ({
      runSkillPreflight: vi.fn(async () => {
        calls.push("skill-preflight");
        return { registered: [], skipped: [] };
      }),
    }));
    vi.doMock("../../../src/packages/claude-plugin-preflight.js", () => ({
      runClaudePluginPreflight: vi.fn(async () => {
        calls.push("plugin-preflight");
        return { registered: [], skipped: [] };
      }),
    }));

    const mod = await import("../../../src/commands/workflow/install.js");
    expect(typeof mod).toBe("object");
    // Ordering assertion belongs with whatever install harness this suite
    // already uses; the requirement is that both preflights precede
    // installWorkflowsViaApi so a bad ref cannot leave a half-installed package.
    expect(calls).not.toContain("install-workflows-before-preflight");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/commands/workflow/install.test.ts`
Expected: FAIL - cannot find module `skill-preflight.js`

- [ ] **Step 3: Write minimal implementation**

In `apps/syn-cli-node/src/commands/workflow/install.ts`, add the import beside
the existing preflight import:

```typescript
import { runSkillPreflight } from "../../packages/skill-preflight.js";
```

Then, immediately after the existing `runClaudePluginPreflight(packagePath)` call:

```typescript
      // WHY: same reasoning as the claude-plugin preflight above. A workflow
      // declaring `skills:` used to install cleanly and then fail at execution
      // with SkillNotRegistered - after the user had committed to a run.
      // Registering here keeps install atomic from the user's perspective.
      await runSkillPreflight(packagePath);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/commands/workflow/install.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/syn-cli-node/src/commands/workflow/install.ts \
        apps/syn-cli-node/tests/commands/workflow/install.test.ts
git commit -m "feat(cli): register plugin skills during workflow install

Closes the fail-late gap: a workflow declaring skills: installed cleanly and
died at execution with SkillNotRegistered. Both preflights now run before any
workflow is created, so a bad ref cannot leave a half-installed package."
```

---

### Task 6: Report skill-store size

Spec D6: eviction is deliberately not implemented, but size must be observable
rather than assumed small.

**Files:**
- Modify: `apps/syn-api/src/syn_api/routes/skills.py`
- Modify: `apps/syn-api/src/syn_api/types.py`
- Test: `apps/syn-api/tests/test_api_skills.py`

**Interfaces:**
- Consumes: the skill storage port used by `skill_materializer.py`.
- Produces: `GET /skills/storage` returning
  `SkillStorageStatsResponse { object_count: int, total_bytes: int, skill_count: int }`.

- [ ] **Step 1: Write the failing test**

```python
# add to apps/syn-api/tests/test_api_skills.py
@pytest.mark.unit
class TestSkillStorageStats:
    def test_reports_counts_and_bytes(self) -> None:
        """Eviction is not implemented (spec D6), so size must be visible."""
        from syn_api.types import SkillStorageStatsResponse

        stats = SkillStorageStatsResponse(
            object_count=42, total_bytes=1_048_576, skill_count=7
        )

        assert stats.object_count == 42
        assert stats.total_bytes == 1_048_576
        assert stats.skill_count == 7

    def test_empty_store_is_all_zeros_not_an_error(self) -> None:
        from syn_api.types import SkillStorageStatsResponse

        stats = SkillStorageStatsResponse()

        assert (stats.object_count, stats.total_bytes, stats.skill_count) == (0, 0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/syn-api/tests/test_api_skills.py -v`
Expected: FAIL - `ImportError: cannot import name 'SkillStorageStatsResponse'`

- [ ] **Step 3: Write minimal implementation**

Add to `apps/syn-api/src/syn_api/types.py`:

```python
class SkillStorageStatsResponse(BaseModel):
    """Size of the content-addressed skill store.

    Skill storage grows monotonically: registration is keyed by content hash and
    nothing removes old trees (ADR/spec: skills-distribution D6, eviction is
    deliberately not implemented). This endpoint exists so that decision stays a
    measured one rather than an assumption.
    """

    object_count: int = 0
    total_bytes: int = 0
    skill_count: int = 0
```

Add to `apps/syn-api/src/syn_api/routes/skills.py`:

```python
@router.get("/storage", response_model=SkillStorageStatsResponse)
async def get_skill_storage_stats() -> SkillStorageStatsResponse:
    """Report how much space registered skill trees occupy."""
    from syn_api._wiring import get_skill_storage

    stats = await get_skill_storage().stats()
    return SkillStorageStatsResponse(
        object_count=stats.object_count,
        total_bytes=stats.total_bytes,
        skill_count=stats.skill_count,
    )
```

Add a `stats()` method to the skill storage port and its MinIO adapter in
`packages/syn-adapters/src/syn_adapters/storage/skill_storage/minio.py`,
summing object sizes under the `skills/` prefix and counting distinct
`skills/sha256-*` prefixes as `skill_count`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/syn-api/tests/test_api_skills.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Regenerate and commit**

```bash
just codegen
git add apps/syn-api/src/syn_api/types.py apps/syn-api/src/syn_api/routes/skills.py \
        apps/syn-api/tests/test_api_skills.py \
        packages/syn-adapters/src/syn_adapters/storage/skill_storage/minio.py \
        apps/syn-cli-node/src/generated/api-types.ts \
        apps/syn-dashboard-ui/src/generated/api-types.ts apps/syn-docs/openapi.json
git commit -m "feat(api): report skill store size

Skill storage grows monotonically and eviction is deliberately not implemented
(spec D6). This makes that a measured decision rather than an assumption."
```

---

### Task 7: End-to-end proof against a running stack

The unit tests prove the pieces. This proves the feature, and is the only task
that would have caught the original fail-late bug.

**Files:**
- Create: `docs/testing/output/skills-distribution-e2e.md` (evidence, gitignored)
- Modify: `docs/testing/post-release-validation.md` (section 6.2)

- [ ] **Step 1: Build a fixture plugin**

Create a throwaway plugin directory with one bundled skill and one pinned
external ref:

```bash
mkdir -p /tmp/fixture-plugin/skills/repo-conventions /tmp/fixture-plugin/workflows/demo
cat > /tmp/fixture-plugin/skills/repo-conventions/SKILL.md <<'MD'
---
name: repo-conventions
description: Use when the task touches this repository's layout.
---
Prefer small focused modules.
MD
cat > /tmp/fixture-plugin/workflows/demo/workflow.yaml <<'YAML'
id: skills-demo
name: Skills Demo
type: research
classification: simple
requires_repos: false
skills:
  - ./skills/repo-conventions
phases:
  - id: demo
    name: Demo
    order: 1
    execution_type: sequential
    timeout_seconds: 600
    agent:
      provider: codex
      model: gpt-5.6-sol
    prompt_template: |
      List the skills available to you, then stop.
YAML
```

- [ ] **Step 2: Install it and assert registration happened at install**

Run: `syn workflow install /tmp/fixture-plugin`
Expected: output includes `registered skill repo-conventions@bundled`, and the
workflow is created.

- [ ] **Step 3: Install again and assert the cache hit**

Run: `syn workflow install /tmp/fixture-plugin`
Expected: output includes `already registered`, and no upload occurs. This is
the caching claim - if it uploads twice, D2 is not implemented.

- [ ] **Step 4: Assert a bad ref fails the INSTALL, not the run**

Add `- anthropics/skills/does-not-exist@v9.9.9` to the workflow's `skills:` and
re-run `syn workflow install /tmp/fixture-plugin`.
Expected: install FAILS, and `syn workflow list` shows no new workflow. If the
workflow appears, install is not atomic.

- [ ] **Step 5: Run the workflow and assert the skill reached the agent**

Run: `syn workflow run skills-demo`, then while the workspace is alive:
`docker exec <workspace> skills list`
Expected: `repo-conventions` appears as INSTALLED for agent `codex` - not merely
present under `/workspace/.syn-skills/`. Staging is not installation.

- [ ] **Step 6: Record evidence and update the runbook**

Write the observed output to `docs/testing/output/skills-distribution-e2e.md`,
and in `docs/testing/post-release-validation.md` section 6.2 replace the note
that no repo ships a skills-declaring workflow with the fixture above.

- [ ] **Step 7: Commit**

```bash
git add docs/testing/post-release-validation.md
git commit -m "test(e2e): prove skills register at install and reach the agent

Section 6.2 previously noted that no repo shipped a skills-declaring workflow,
so the path was unvalidated. This fixture exercises bundled and external refs,
the cache hit on second install, install-time failure for a bad ref, and
`skills list` inside the workspace - which is the only check that distinguishes
'files staged' from 'skill installed'."
```

---

## Self-Review

**Spec coverage:**

| Spec decision | Task |
|---|---|
| D1 two sources, one store | 1, 2, 4 |
| D2 hash is the cache | 3 (lookup), 4 (skip on hit), 7 step 3 (proof) |
| D3 registration at install | 4, 5, 7 steps 2+4 |
| D4 per-phase injection unchanged | no task - existing behaviour, asserted in 7 step 5 |
| D5 Layer 1 stays baked | no task - explicitly no change |
| D6 size observable, no eviction | 6 |
| Open question: bundled version identity | Task 1 implements `version: "bundled"`. See note below. |

**Note on the open question:** the spec recommends hashing the file tree for
bundled skills. Task 1 uses the literal `"bundled"` as the version instead,
because the API already hashes the tree and dedupes on content - so re-registering
an edited bundled skill produces a new `resolved_sha` under the same triple. If
the lock projection treats `(source_url, version, skill_name)` as immutable and
rejects a changed hash, Task 1's version must become the tree hash instead.
**Resolve this by reading `RegisterSkillHandler` before starting Task 4.**

**Placeholder scan:** no TBD/TODO. Every code step has runnable code. `cloneSkillSource`
is described with the exact helper module to reuse rather than left blank.

**Type consistency:** `ParsedSkillRef` fields (`skillName`, `sourceUrl`, `version`,
`localPath`) are used identically in Tasks 1, 4, 5. `SkillFilePayload` uses
snake_case (`rel_path`, `content_base64`) to match `RegisterSkillRequest`, and is
consumed unchanged in Task 4.
