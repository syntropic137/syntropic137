# Harness-Agnostic Skill Injection (Plan 1 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Workflows can declare `skills:` (SKILL.md folders) at workflow and phase scope, and those skills are registered content-addressed in MinIO, materialized into the workspace, and installed for the phase's harness (claude/codex/gemini) via the pinned vercel `skills` CLI.

**Architecture:** Mirror the existing claude_plugins pipeline (issue #726) with the unit changed from plugin to skill, ADDITIVELY - claude_plugins keeps working until Plan 3 removes it. New: an in-container install step (`skills add <local-path> --agent <harness> -y`) replaces `--plugin-dir` flag emission, making injection harness-agnostic. Spec: GitHub issue syntropic137/syntropic137#772.

**Tech Stack:** Python (pydantic v2, event sourcing via `event_sourcing` lib), MinIO, Docker, vercel-labs `skills` npm CLI (pinned `1.5.14`).

**Worktree:** All work happens in `/Users/neural/Code/Syntropic137/syntropic137_worktrees/20260703_772-skills-injection` on branch `feat/772-skills-injection`. All paths below are relative to that root.

## Global Constraints

- Strict typing: pyright standard mode must pass; no `Any` without justification; Pydantic models `frozen=True, extra="forbid"` (ADR-001 s6, ADR-032).
- No em dashes in any file; plain hyphens only.
- All TODO/FIXME comments must reference a GitHub issue: `# TODO(#772): ...`.
- Pin exact versions: the `skills` npm package is `1.5.14` everywhere it appears.
- In-memory adapters MUST inherit `InMemoryAdapter` (ADR-060).
- API routes MUST use Pydantic response models, never `dict[str, Any]`.
- `@latest` / unpinned skill refs are rejected (reproducibility).
- Skill identity/lock key is `(source_url, version, skill_name)`.
- Run `uv run pytest <file> -x -q` from the repo root for tests; `just fitness-check` before pushing.
- Commit after every green task with conventional commit messages.
- The existing claude_plugins pipeline MUST remain untouched and green in this plan (removal is Plan 3).

## Plan Sequence (context for this plan)

- **Plan 1 (this document):** domain + storage + resolution + provisioning + images. After this plan a workflow seeded via the API with `skills:` executes with skills installed for its harness.
- **Plan 2 (separate):** CLI surface (`syn skill` command group, install pre-flight walking `skills:`), API list/show routes, docs site pages.
- **Plan 3 (separate):** remove `claude_plugins` (field, slices, bucket, `--plugin-dir` emission), new ADR superseding ADR-065, repoint docs.

## Reference Files (read before starting any task)

The skills pipeline deliberately mirrors these existing files. When a task says "mirror X", open X and preserve its structure, docstring style, and defensive checks, applying the rename table:

| Existing (claude_plugins) | New (skills) |
|---|---|
| `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/claude_plugin_ref.py` | `_shared/skill_ref.py` |
| `_shared/resolved_claude_plugin.py` | `_shared/resolved_skill.py` |
| `_shared/claude_plugin_errors.py` | `_shared/skill_errors.py` |
| `ports/ClaudePluginStoragePort.py` | `ports/SkillStoragePort.py` |
| `domain/aggregate_claude_plugin_registration/ClaudePluginRegistrationAggregate.py` | `domain/aggregate_skill_registration/SkillRegistrationAggregate.py` |
| `slices/register_claude_plugin/` | `slices/register_skill/` |
| `packages/syn-adapters/src/syn_adapters/storage/claude_plugin_storage/{minio,memory,factory}.py` | `.../storage/skill_storage/{minio,memory,factory}.py` |
| `apps/syn-api/src/syn_api/services/claude_plugin_materializer.py` | `apps/syn-api/src/syn_api/services/skill_materializer.py` |
| `apps/syn-api/src/syn_api/services/claude_plugin_resolution_service.py` | `apps/syn-api/src/syn_api/services/skill_resolution_service.py` |
| `apps/syn-api/src/syn_api/routes/claude_plugins.py` | `apps/syn-api/src/syn_api/routes/skills.py` |
| `ClaudePluginFile` / `StoredClaudePluginTree` | `SkillFile` / `StoredSkillTree` |
| `ClaudePluginRef` | `SkillRef` |
| `ResolvedClaudePlugin` | `ResolvedSkill` |
| manifest `.claude-plugin/plugin.json` | manifest `SKILL.md` (YAML frontmatter) |
| workspace root `.syn-plugins/` | workspace root `.syn-skills/` |
| setting `claude_plugin_bucket_name` (`SYN_STORAGE_CLAUDE_PLUGIN_BUCKET_NAME`) | setting `skill_bucket_name` (`SYN_STORAGE_SKILL_BUCKET_NAME`, default `"skills"`) |
| flag `DEV__WORKFLOW_FAIL_ON_PLUGIN_NOT_REGISTERED` | flag `DEV__WORKFLOW_FAIL_ON_SKILL_NOT_REGISTERED` (default `True`) |

---

### Task 1: `SkillRef` value object

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/skill_ref.py`
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_skill_ref.py`

**Interfaces:**
- Produces: `class SkillRef(BaseModel)` with fields `skill_name: str`, `source_url: str`, `version: str`, `name_overridden: bool = False`; frozen; `__eq__`/`__hash__` over `(source_url, version, skill_name)`; module-level `def expand_skill_entry(entry: object) -> list[SkillRef]` that turns one YAML list entry into one or more refs.

Accepted YAML forms (spec section 2):

1. String shorthand `org/repo/skill-name@version` (three path segments; the third is the skill folder name inside the repo).
2. String full URL `<url>@<version>` - names the repo only; skill name defaults to the URL basename (single-skill repos).
3. Verbose mapping `{source|source_url, version, names: [a, b]}` or `{source, version, name: a}` - `names` expands to N refs sharing source and version.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for SkillRef parsing (issue #772)."""

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillRef,
    expand_skill_entry,
)


class TestShorthandForm:
    def test_org_repo_skill_at_version(self) -> None:
        ref = SkillRef.model_validate("anthropics/skills/frontend-design@v1.2.0")
        assert ref.skill_name == "frontend-design"
        assert ref.source_url == "https://github.com/anthropics/skills"
        assert ref.version == "v1.2.0"
        assert ref.name_overridden is False

    def test_two_segment_shorthand_rejected(self) -> None:
        # org/repo@version is ambiguous for skills (which skill in the repo?);
        # require the third segment or the verbose form.
        with pytest.raises(ValidationError, match="org/repo/skill-name@version"):
            SkillRef.model_validate("anthropics/skills@v1.2.0")

    def test_latest_rejected(self) -> None:
        with pytest.raises(ValidationError, match="latest"):
            SkillRef.model_validate("anthropics/skills/frontend-design@latest")


class TestUrlForm:
    def test_url_at_version_uses_basename_as_skill_name(self) -> None:
        ref = SkillRef.model_validate("https://github.com/acme/tdd-skill@v2.0.0")
        assert ref.skill_name == "tdd-skill"
        assert ref.source_url == "https://github.com/acme/tdd-skill"
        assert ref.version == "v2.0.0"

    def test_missing_version_rejected(self) -> None:
        with pytest.raises(ValidationError, match="missing '@<version>'"):
            SkillRef.model_validate("https://github.com/acme/tdd-skill")


class TestVerboseForm:
    def test_single_name(self) -> None:
        ref = SkillRef.model_validate(
            {"source": "github.com/acme/agent-skills", "version": "v2.0.0", "name": "code-review"}
        )
        assert ref.skill_name == "code-review"
        assert ref.source_url == "https://github.com/acme/agent-skills"
        assert ref.name_overridden is True


class TestExpandSkillEntry:
    def test_names_list_expands(self) -> None:
        refs = expand_skill_entry(
            {
                "source": "https://github.com/acme/agent-skills",
                "version": "v2.0.0",
                "names": ["code-review", "tdd-workflow"],
            }
        )
        assert [r.skill_name for r in refs] == ["code-review", "tdd-workflow"]
        assert all(r.source_url == "https://github.com/acme/agent-skills" for r in refs)
        assert all(r.version == "v2.0.0" for r in refs)

    def test_string_entry_yields_single_ref(self) -> None:
        refs = expand_skill_entry("anthropics/skills/frontend-design@v1.2.0")
        assert len(refs) == 1
        assert refs[0].skill_name == "frontend-design"

    def test_empty_names_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="'names' must be a non-empty list"):
            expand_skill_entry({"source": "github.com/a/b", "version": "v1", "names": []})


class TestIdentity:
    def test_eq_and_hash_by_source_version_name(self) -> None:
        a = SkillRef.model_validate("acme/skills/foo@v1")
        b = SkillRef.model_validate(
            {"source": "https://github.com/acme/skills", "version": "v1", "name": "foo"}
        )
        assert a == b
        assert hash(a) == hash(b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_skill_ref.py -x -q`
Expected: FAIL with `ModuleNotFoundError: ... skill_ref`

- [ ] **Step 3: Implement `skill_ref.py`**

Mirror `claude_plugin_ref.py` (same helpers: `_normalize_source`, `_basename_from_url`, `_parse_url_form`, `_reject_latest_version`, `__get_pydantic_json_schema__` publishing the anyOf schema). Differences, in full:

```python
# Anchored shorthand parser: org/repo/skill-name@version.
_SKILL_SHORTHAND_RE = re.compile(r"^([^/@\s]+)/([^/@\s]+)/([^/@\s]+)@(.+)$")

# Two-segment form is a plugin-era shape; give a corrective error.
_TWO_SEGMENT_RE = re.compile(r"^([^/@\s]+)/([^/@\s]+)@(.+)$")


def _try_parse_skill_shorthand(raw: str) -> _ParsedRefDict | None:
    if "://" in raw or raw.startswith("git@"):
        return None
    match = _SKILL_SHORTHAND_RE.match(raw)
    if match is not None:
        org, repo, skill, version = match.groups()
        return {
            "skill_name": skill,
            "source_url": f"https://github.com/{org}/{repo}",
            "version": version,
            "name_overridden": False,
        }
    if _TWO_SEGMENT_RE.match(raw) is not None:
        msg = (
            f"skill reference {raw!r} names a repo but not a skill; "
            "expected 'org/repo/skill-name@version' or the verbose mapping form"
        )
        raise ValueError(msg)
    return None


def expand_skill_entry(entry: object) -> list[SkillRef]:
    """Expand one YAML ``skills:`` list entry into one or more SkillRefs.

    The verbose mapping form accepts ``names: [a, b]`` to declare several
    skills from one source; every other form yields exactly one ref.
    """
    if isinstance(entry, dict) and "names" in entry:
        names = entry["names"]
        if not isinstance(names, list) or not names:
            msg = "skill verbose form 'names' must be a non-empty list of strings"
            raise ValueError(msg)
        base = {k: v for k, v in entry.items() if k != "names"}
        return [SkillRef.model_validate({**base, "name": name}) for name in names]
    return [SkillRef.model_validate(entry)]
```

`_ParsedRefDict` uses `skill_name` instead of `name`; `_parse_dict_form` maps the verbose `name` key onto `skill_name` (keep accepting `source` or `source_url`). `_parse_url_form` sets `skill_name` from `_basename_from_url`. All error messages say "skill reference", not "claude plugin reference". Model:

```python
class SkillRef(BaseModel):
    """A workflow-declared reference to an agent skill (issue #772).

    Compared and hashed by ``(source_url, version, skill_name)`` to match
    the lock projection key. A repo publishing many skills produces one
    ref (and one lock entry) per declared skill.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    name_overridden: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_skill_ref.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/skill_ref.py \
        packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_skill_ref.py
git commit -m "feat(skills): SkillRef value object with three-segment shorthand (#772)"
```

---

### Task 2: `ResolvedSkill` VO and `skill_errors.py`

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/resolved_skill.py`
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/skill_errors.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class ResolvedSkill` with `skill_name: str, source_url: str, version: str, resolved_sha: str, tree_storage_prefix: str`. Errors: `SkillError(Exception)` base, `SkillInvalidName(SkillError)`, `SkillInvalidPath(SkillError)`, `SkillManifestMissing(SkillError)`, `SkillManifestInvalid(SkillError)`, `SkillNotRegistered(SkillError)`, `SkillInstallFailed(SkillError)`.

- [ ] **Step 1: Create `resolved_skill.py`** - mirror `resolved_claude_plugin.py` verbatim with the rename table applied (docstring cites issue #772 and `<workspace>/.syn-skills/<skill_name>/`).

- [ ] **Step 2: Create `skill_errors.py`** - mirror `claude_plugin_errors.py` structure (each error carries the offending value and a reason string in its message). Add the two new ones:

```python
class SkillNotRegistered(SkillError):
    """A workflow declared a skill that has no lock entry."""

    def __init__(self, source_url: str, version: str, skill_name: str) -> None:
        super().__init__(
            f"skill {skill_name!r} from {source_url}@{version} is not registered; "
            "register it first (Plan 2: 'syn skill add', or POST /skills/registrations)"
        )


class SkillInstallFailed(SkillError):
    """The in-container 'skills add' invocation exited nonzero."""

    def __init__(self, skill_name: str, agent: str, exit_code: int, stderr: str) -> None:
        super().__init__(
            f"installing skill {skill_name!r} for agent {agent!r} failed "
            f"(exit {exit_code}): {stderr.strip()[:500]}"
        )
```

- [ ] **Step 3: Verify imports and typing**

Run: `uv run pyright packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/resolved_skill.py packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/skill_errors.py`
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/resolved_skill.py \
        packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/skill_errors.py
git commit -m "feat(skills): ResolvedSkill VO and skill error taxonomy (#772)"
```

---

### Task 3: `SkillStoragePort` + MinIO/memory adapters + bucket setting

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/SkillStoragePort.py`
- Create: `packages/syn-adapters/src/syn_adapters/storage/skill_storage/__init__.py`
- Create: `packages/syn-adapters/src/syn_adapters/storage/skill_storage/minio.py`
- Create: `packages/syn-adapters/src/syn_adapters/storage/skill_storage/memory.py`
- Create: `packages/syn-adapters/src/syn_adapters/storage/skill_storage/factory.py`
- Modify: `packages/syn-shared/src/syn_shared/settings/storage.py` (add `skill_bucket_name` next to `claude_plugin_bucket_name`, around line 102)
- Test: `packages/syn-adapters/src/syn_adapters/storage/skill_storage/test_skill_storage.py` (mirror the claude_plugin_storage tests, same directory pattern)

**Interfaces:**
- Produces: `SkillFile(rel_path: str, content: bytes)`, `StoredSkillTree(storage_prefix, sha256, file_count, total_size_bytes, metadata)`, `SkillStoragePort` Protocol with `upload_tree(sha256, files) -> StoredSkillTree`, `fetch_tree(sha256) -> list[SkillFile]`, `exists(sha256) -> bool`, `prefix_for(sha256) -> str`, `ensure_ready() -> None`. Factory: `create_skill_storage(settings) -> SkillStoragePort`.

- [ ] **Step 1: Port** - mirror `ClaudePluginStoragePort.py` with the rename table. Docstring: "A skill is a directory tree containing `SKILL.md` with YAML frontmatter (name, description), per the vercel-labs/skills convention. Trees land in workspaces at `<workspace>/.syn-skills/<skill_name>/<rel_path>`."

- [ ] **Step 2: Settings field** in `StorageSettings`:

```python
skill_bucket_name: str = Field(
    default="skills",
    description="Bucket for content-addressed skill trees (issue #772)",
)
```

Then regenerate the env example: `just codegen` (or the narrower recipe if one exists; check `just --list | grep -i env`). Expected: `.env.example` gains `SYN_STORAGE_SKILL_BUCKET_NAME=skills`.

- [ ] **Step 3: Adapters** - mirror `claude_plugin_storage/minio.py`, `memory.py`, `factory.py` exactly (object layout `skills/sha256-<hash>/files/<rel-path>` plus `manifest.json`; memory adapter MUST inherit `InMemoryAdapter` from `syn_adapters.in_memory`; factory selects on `settings.storage.provider` the same way, reading `settings.storage.skill_bucket_name`).

- [ ] **Step 4: Tests** - mirror the existing claude_plugin_storage tests (find them with `ls packages/syn-adapters/src/syn_adapters/storage/claude_plugin_storage/`); cover upload/fetch round-trip, `exists`, `prefix_for` consistency, and memory-adapter environment guard.

Run: `uv run pytest packages/syn-adapters/src/syn_adapters/storage/skill_storage/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add packages/syn-domain/src/syn_domain/contexts/orchestration/ports/SkillStoragePort.py \
        packages/syn-adapters/src/syn_adapters/storage/skill_storage/ \
        packages/syn-shared/src/syn_shared/settings/storage.py .env.example
git commit -m "feat(skills): SkillStoragePort with MinIO and in-memory adapters (#772)"
```

---

### Task 4: `SkillRegistrationAggregate` + `register_skill` slice

**Files:**
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_skill_registration/__init__.py`
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_skill_registration/SkillRegistrationAggregate.py`
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/commands/RegisterSkillCommand.py` (mirror `RegisterClaudePluginCommand.py` in the same directory)
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/SkillRegistrationRepositoryPort.py` (mirror `ClaudePluginRegistrationRepositoryPort.py`)
- Create: `packages/syn-adapters/src/syn_adapters/storage/in_memory_skill_repositories.py` (mirror `in_memory_claude_plugin_repositories.py`)
- Create: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/register_skill/{__init__.py,RegisterSkillHandler.py,projection.py,slice.yaml,test_register_skill.py,test_register_skill_concurrency.py}`
- Test: aggregate test mirroring `test_claude_plugin_registration_aggregate.py`

**Interfaces:**
- Consumes: `SkillFile`, `SkillStoragePort` (Task 3); `SkillInvalidPath`, `SkillManifestMissing`, `SkillManifestInvalid` (Task 2).
- Produces: `RegisterSkillHandler.handle(source_url: str, version: str, skill_name: str | None, files: list[SkillFile]) -> RegisterSkillResult` where `RegisterSkillResult(skill_name, source_url, version, resolved_sha, tree_storage_prefix)`; `SkillRegistrationAggregate.compute_stream_id(source_url, version, skill_name) -> str`; lock projection `SkillLockProjection` exposing `async get(source_url, version, skill_name) -> SkillLockEntry | None` with `SkillLockEntry(skill_name, source_url, version, resolved_sha, tree_storage_prefix)`.

Mirror the plugin counterparts throughout (immutable aggregate, first-writer-wins, `StreamAlreadyExistsError` race recovery, `_compute_tree_sha` sorted-tree hashing, `_validate_tree_paths` rejection rules). The ONE semantic difference is manifest handling: the manifest is `SKILL.md` frontmatter, not `plugin.json`.

- [ ] **Step 1: Write the failing handler tests** (mirror `test_register_claude_plugin.py`, plus these skill-specific cases)

```python
SKILL_MD = b"""---
name: code-review
description: Review diffs for correctness bugs.
---

# Code Review

Instructions here.
"""


async def test_register_skill_happy_path(handler: RegisterSkillHandler) -> None:
    result = await handler.handle(
        source_url="https://github.com/acme/agent-skills",
        version="v2.0.0",
        skill_name=None,
        files=[SkillFile(rel_path="SKILL.md", content=SKILL_MD)],
    )
    assert result.skill_name == "code-review"  # frontmatter name wins when no override
    assert len(result.resolved_sha) == 64


async def test_missing_skill_md_rejected(handler: RegisterSkillHandler) -> None:
    with pytest.raises(SkillManifestMissing):
        await handler.handle(
            source_url="https://github.com/acme/agent-skills",
            version="v2.0.0",
            skill_name="x",
            files=[SkillFile(rel_path="README.md", content=b"nope")],
        )


async def test_frontmatter_without_name_rejected(handler: RegisterSkillHandler) -> None:
    bad = b"---\ndescription: no name here\n---\nbody"
    with pytest.raises(SkillManifestInvalid, match="frontmatter must declare 'name'"):
        await handler.handle(
            source_url="https://github.com/acme/agent-skills",
            version="v2.0.0",
            skill_name=None,
            files=[SkillFile(rel_path="SKILL.md", content=bad)],
        )
```

- [ ] **Step 2: Run to verify failure** - `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/slices/register_skill/ -x -q` - FAIL (module missing).

- [ ] **Step 3: Implement.** In `RegisterSkillHandler.py`, replace `_extract_plugin_manifest` with:

```python
_MANIFEST_PATH = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _extract_skill_frontmatter(
    files: list[SkillFile],
    source_url: str,
    version: str,
) -> dict[str, object]:
    """Parse the YAML frontmatter of the tree's root SKILL.md.

    A skill tree is one skill folder; SKILL.md MUST sit at the tree root.
    Frontmatter MUST declare a non-empty ``name`` (lowercase, hyphens) and
    ``description``, per the vercel-labs/skills convention.
    """
    manifest_file = next((f for f in files if f.rel_path == _MANIFEST_PATH), None)
    if manifest_file is None:
        raise SkillManifestMissing(source_url, version)
    try:
        text = manifest_file.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillManifestInvalid(source_url, version, str(exc)) from exc
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise SkillManifestInvalid(source_url, version, "SKILL.md has no YAML frontmatter block")
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SkillManifestInvalid(source_url, version, str(exc)) from exc
    if not isinstance(parsed, dict):
        raise SkillManifestInvalid(source_url, version, "frontmatter must be a YAML mapping")
    frontmatter = {str(k): v for k, v in parsed.items() if isinstance(k, str)}
    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SkillManifestInvalid(source_url, version, "frontmatter must declare 'name'")
    return frontmatter
```

(`import yaml` - PyYAML is already a workspace dependency; verify with `uv run python -c "import yaml"`. If it is not a direct dependency of syn-domain, add `pyyaml==<currently-resolved-version>` to `packages/syn-domain/pyproject.toml` per the exact-pin rule; find the resolved version with `uv pip show pyyaml`.)

Name resolution order (mirrors `_resolve_effective_name`): explicit `skill_name` arg wins, then frontmatter `name`, then URL basename. Everything else (stream id, sha, upload-skip on `exists`, race recovery, projection) is a straight mirror.

`slice.yaml`: copy `register_claude_plugin/slice.yaml` and rename the slice, command, and events (`SkillRegistered` event).

- [ ] **Step 4: Run all new tests + aggregate tests** - `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/slices/register_skill/ packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_skill_registration/ -q` - PASS.

- [ ] **Step 5: VSA validation** - `just vsa-validate` (or `uv run vsa validate` per the justfile). Expected: the new slice passes bounded-context conventions.

- [ ] **Step 6: Commit**

```bash
git add packages/syn-domain packages/syn-adapters
git commit -m "feat(skills): SkillRegistrationAggregate and register_skill slice (#772)"
```

---

### Task 5: `skills:` in workflow YAML + `ExecutablePhase.skills`

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py` (phase model ~line 227, `to_phase_definition` ~line 276, workflow model ~line 353)
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/value_objects.py` (~line 198)
- Test: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_workflow_yaml_skills.py` (mirror `test_workflow_yaml_claude_plugins.py`)

**Interfaces:**
- Consumes: `SkillRef`, `expand_skill_entry` (Task 1); `ResolvedSkill` (Task 2).
- Produces: `PhaseYamlDefinition.skills: list[SkillRef]` and `WorkflowYamlDefinition.skills: list[SkillRef]` (both `Field(default_factory=list)`), populated through a `field_validator(mode="before")` that maps `expand_skill_entry` over the raw list; `ExecutablePhase.skills: tuple[ResolvedSkill, ...] = ()`; phase-level refs are additive on top of workflow-level refs with phase scope winning on identity collision (same merge logic as `claude_plugins` - find it by grepping `claude_plugins` in `workflow_definition.py` and `yaml_to_command.py` and mirror every site).

- [ ] **Step 1: Write failing tests** covering: workflow-level only, phase-level only, both (additive, dedup by identity), `names:` expansion inside YAML, `@latest` rejection surfacing as a workflow parse error. Copy the fixtures pattern from `test_workflow_yaml_claude_plugins.py` and change the field name and shorthand forms (three-segment).

- [ ] **Step 2: Verify failure** - `uv run pytest .../test_workflow_yaml_skills.py -x -q`.

- [ ] **Step 3: Implement.** Grep first: `grep -rn "claude_plugins" packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/` - every hit in `workflow_definition.py`, `yaml_to_command.py`, and `value_objects.py` gets a parallel `skills` line added immediately below it (do NOT modify the claude_plugins lines). The before-validator on both models:

```python
@field_validator("skills", mode="before")
@classmethod
def _expand_skills(cls, value: object) -> object:
    if not isinstance(value, list):
        return value
    expanded: list[SkillRef] = []
    for entry in value:
        expanded.extend(expand_skill_entry(entry))
    return expanded
```

- [ ] **Step 4: Run the new tests AND the existing plugin YAML tests** (regression guard):

`uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ -q` - all PASS.

- [ ] **Step 5: Commit** - `git commit -am "feat(skills): skills field at workflow and phase scope (#772)"`

---

### Task 6: Seed-time validation + `DEV__WORKFLOW_FAIL_ON_SKILL_NOT_REGISTERED`

**Files:**
- Modify: `packages/syn-shared/src/syn_shared/settings/dev_tooling.py` (add flag next to `workflow_fail_on_plugin_not_registered`, ~line 64)
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/seed_workflow/SeedWorkflowService.py` (mirror `_validate_plugins` / `_ClaudePluginResolver.ensure_registered`, lines ~46-54, 124-146, 228-255)
- Test: extend the existing seed tests in the same slice (find with `ls packages/syn-domain/src/syn_domain/contexts/orchestration/slices/seed_workflow/`)

**Interfaces:**
- Consumes: `SkillLockProjection.get(...)` (Task 4), `SkillNotRegistered` (Task 2).
- Produces: seeding a workflow whose `skills:` include an unregistered ref raises `SkillNotRegistered` when the flag is `True` (default). The service grows a `_validate_skills` mirroring `_validate_plugins`, walking workflow-level plus every phase's refs, deduped by identity.

- [ ] **Step 1: Failing test** - seed a definition with one unregistered skill ref, assert `SkillNotRegistered`; register it (via the Task 4 handler against in-memory adapters), re-seed, assert success.
- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement** (flag default `True`, description mirrors the plugin flag's; validation call sits directly after `_validate_plugins` in the seed path).
- [ ] **Step 4: Run the whole seed slice test file** - PASS.
- [ ] **Step 5: Commit** - `git commit -am "feat(skills): fail seeding on unregistered skills (#772)"`

---

### Task 7: Skill resolution service + API registration route + wiring

**Files:**
- Create: `apps/syn-api/src/syn_api/services/skill_resolution_service.py` (mirror `claude_plugin_resolution_service.py`: reads the lock projection, turns each phase's `SkillRef`s - workflow-scope merged with phase-scope - into `ResolvedSkill`s on `ExecutablePhase.skills`)
- Create: `apps/syn-api/src/syn_api/routes/skills.py` (mirror `routes/claude_plugins.py`: `POST /skills/registrations` accepting `{source_url, version, skill_name?, files: [{rel_path, content_base64}]}`, returning the lock-entry fields; reuse its error-mapping pattern from `services/claude_plugin_error_mapping.py` with a sibling `skill_error_mapping.py`)
- Modify: `apps/syn-api/src/syn_api/types.py` (add `RegisterSkillRequest`, `SkillFilePayload`, `SkillRegistrationResponse` - mirror the plugin request/response models found by grepping `ClaudePlugin` in that file)
- Modify: `apps/syn-api/src/syn_api/_wiring.py` (construct storage via `create_skill_storage`, repositories, handler, resolution service - one parallel line per `claude_plugin` wiring line; grep `claude_plugin` in `_wiring.py`)
- Modify: `apps/syn-api/src/syn_api/lifecycle.py` (call `ensure_ready()` on skill storage at startup next to the plugin bucket init - ADR-012 pattern)
- Test: mirror the claude_plugins route tests (find them with `grep -rln "claude-plugins/registrations" apps/syn-api`)

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: `SkillResolutionService.resolve_for_execution(definition) -> ...` populating `ExecutablePhase.skills`; HTTP `POST /skills/registrations`. Route return type MUST be the Pydantic response model (OpenAPI pipeline rule).

- [ ] **Step 1: Failing route test** - POST a one-file SKILL.md tree, assert 200 with `skill_name`, `resolved_sha`; POST again, assert idempotent same sha; POST with traversal rel_path `../evil`, assert 422.
- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement** service, route, types, wiring, lifecycle init.
- [ ] **Step 4: Run** the route tests plus `uv run pytest apps/syn-api -q -k "skill"` - PASS. Then `just docs-sync` to regenerate the OpenAPI spec and confirm no drift-check failure.
- [ ] **Step 5: Commit** - `git commit -am "feat(skills): registration API route, resolution service, wiring (#772)"`

---

### Task 8: `SkillMaterializer`

**Files:**
- Create: `apps/syn-api/src/syn_api/services/skill_materializer.py`
- Test: mirror the materializer tests (find with `grep -rln "ClaudePluginMaterializer" apps/syn-api | grep test`)

**Interfaces:**
- Consumes: `SkillStoragePort.fetch_tree` (Task 3), `ResolvedSkill` (Task 2), `SkillInvalidName` (Task 2).
- Produces: `class SkillMaterializer` with `async fetch_for_workspace(skills: tuple[ResolvedSkill, ...]) -> list[tuple[str, bytes]]` returning paths prefixed `".syn-skills/<skill_name>/"`; module constant `WORKSPACE_SKILL_ROOT = ".syn-skills"`.

- [ ] **Step 1-4:** Mirror `claude_plugin_materializer.py` in full (LRU cache keyed by `resolved_sha`, `_DEFAULT_CACHE_SIZE = 16`, name validation before any fetch, immutable tuple snapshots), with the rename table applied. Tests: happy path prefixing, hostile name rejection before fetch, LRU eviction, cache hit skips storage. Run - PASS.
- [ ] **Step 5: Commit** - `git commit -am "feat(skills): workspace skill materializer (#772)"`

---

### Task 9: Provisioning - materialize + install skills per harness (the genuinely new logic)

**Files:**
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py`
- Test: extend the handler's existing test file (find with `grep -rln "WorkspaceProvisionHandler" --include="test_*.py" packages/`)

**Interfaces:**
- Consumes: `ExecutablePhase.skills` (Task 5), `SkillMaterializer` shape (Task 8), `ManagedWorkspace.execute(command, timeout_seconds=...) -> ExecutionResult` (existing, `managed_workspace.py:90`), `phase.agent_config.agent_id` (existing, `value_objects.py:77`), `SkillInstallFailed` (Task 2).
- Produces: skills materialized into `/workspace/.syn-skills/` and installed for the phase's harness. FAIL-FAST semantics (unlike the plugin path's warn-and-continue).

- [ ] **Step 1: Write failing tests**

```python
async def test_skills_installed_for_phase_agent(handler_with_fake_workspace) -> None:
    # phase.skills = (ResolvedSkill(skill_name="code-review", ...),), agent_id="codex"
    await handler.handle(todo, phase, workflow_id, session_id)
    fake_workspace.execute.assert_awaited_with(
        ["skills", "add", "/workspace/.syn-skills/code-review", "--agent", "codex", "-y"],
        timeout_seconds=120,
    )


async def test_skill_install_failure_raises(handler_with_fake_workspace) -> None:
    fake_workspace.execute.return_value = ExecutionResult(exit_code=1, stdout="", stderr="boom")
    with pytest.raises(SkillInstallFailed, match="code-review"):
        await handler.handle(todo, phase, workflow_id, session_id)


async def test_skills_declared_but_no_materializer_raises(handler_without_materializer) -> None:
    with pytest.raises(RuntimeError, match="no skill materializer is wired"):
        await handler.handle(todo, phase, workflow_id, session_id)


async def test_unknown_agent_id_raises(handler_with_fake_workspace) -> None:
    # agent_id="mystery" must fail before any install attempt
    with pytest.raises(SkillInstallFailed, match="no skills-cli agent key"):
        await handler.handle(todo, phase, workflow_id, session_id)
```

(Adapt fixture names to the existing test file's conventions; `ExecutionResult` import comes from wherever `managed_workspace.py` imports it.)

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Implement.** Add to `WorkspaceProvisionHandler.py`:

```python
# Maps our phase agent_id values onto the vercel skills-cli --agent keys.
# The skills CLI (pinned 1.5.14 in the workspace images) owns the per-harness
# install location; we only translate our identifier vocabulary to theirs.
# Verify against `skills add --help` inside the image whenever the pin bumps.
_SKILLS_CLI_AGENT_KEYS: dict[str, str] = {
    "claude": "claude-code",
    "codex": "codex",
    "gemini": "gemini-cli",
}

_SKILL_INSTALL_TIMEOUT_SECONDS = 120
```

Constructor gains `skill_materializer: SkillMaterializerProtocol | None = None` (a structural `Protocol` in the `TYPE_CHECKING` block, mirroring `ClaudePluginMaterializerProtocol` at line 49 but for `ResolvedSkill`). In `handle()`, insert after `self._materialize_claude_plugins(workspace, phase)` (line 286):

```python
await self._materialize_and_install_skills(workspace, phase)
```

New methods:

```python
async def _materialize_and_install_skills(
    self,
    workspace: ManagedWorkspace,
    phase: ExecutablePhase,
) -> None:
    """Inject skill trees and install them for the phase's harness (issue #772).

    Unlike the plugin path, this FAILS FAST: a phase that declares skills
    must get them or must not run. Silent skill-less execution produces
    confusing agent behavior that is worse than a loud provisioning error.
    """
    if not phase.skills:
        return
    if self._skill_materializer is None:
        msg = (
            f"phase {phase.phase_id} declares skills but no skill materializer "
            "is wired; refusing to run the agent without them (issue #772)"
        )
        raise RuntimeError(msg)
    agent_key = _SKILLS_CLI_AGENT_KEYS.get(phase.agent_config.agent_id)
    if agent_key is None:
        raise SkillInstallFailed(
            phase.skills[0].skill_name,
            phase.agent_config.agent_id,
            exit_code=-1,
            stderr=f"no skills-cli agent key for agent_id {phase.agent_config.agent_id!r}",
        )
    skill_files = await self._skill_materializer.fetch_for_workspace(phase.skills)
    if skill_files:
        await workspace.inject_files(skill_files)
    for skill in phase.skills:
        result = await workspace.execute(
            [
                "skills",
                "add",
                f"/workspace/.syn-skills/{skill.skill_name}",
                "--agent",
                agent_key,
                "-y",
            ],
            timeout_seconds=_SKILL_INSTALL_TIMEOUT_SECONDS,
        )
        if result.exit_code != 0:
            raise SkillInstallFailed(
                skill.skill_name, agent_key, result.exit_code, result.stderr or result.stdout or ""
            )
    logger.info(
        "Installed %d skill(s) for agent %s in %s",
        len(phase.skills),
        agent_key,
        workspace.workspace_id,
    )
```

Note the install runs AFTER `run_setup_phase` (secrets already cleared) and works on both the `claude -p` path and the interactive-tmux path - it is a plain `execute()`, independent of how the agent is later driven. `SkillInstallFailed` import goes at module top (it is used at runtime, not just for typing).

- [ ] **Step 4: Run the handler test file** - all PASS, including the existing plugin tests untouched.

- [ ] **Step 5: Wire the materializer** - in `apps/syn-api/src/syn_api/_wiring.py`, pass the Task 8 `SkillMaterializer` instance into `WorkspaceProvisionHandler(...)` wherever `claude_plugin_materializer=` is passed (grep it). Run `uv run pytest apps/syn-api -q -k "wiring or provision"` - PASS.

- [ ] **Step 6: Commit** - `git commit -am "feat(skills): harness-agnostic skill install at provision time (#772)"`

---

### Task 10: Bake the pinned `skills` CLI into workspace images (agentic-primitives submodule)

**Files (inside `lib/agentic-primitives` - this is our own submodule; commit there directly, then bump the pin here):**
- Modify: `lib/agentic-primitives/providers/workspaces/claude-cli/Dockerfile`
- Modify: `lib/agentic-primitives/providers/workspaces/interactive-tmux/Dockerfile`

**Interfaces:**
- Produces: `skills` binary on PATH inside both images, exact version `1.5.14`.

- [ ] **Step 1:** In each Dockerfile, add next to the existing npm global installs (interactive-tmux already has `npm install -g @openai/codex@0.139.0`; match that style):

```dockerfile
RUN npm install -g skills@1.5.14
```

- [ ] **Step 2: Local build BEFORE any push** (hard rule from prior incidents):

```bash
docker build -t agentic-workspace-claude-cli:skills-test lib/agentic-primitives/providers/workspaces/claude-cli/
docker build -t agentic-workspace-interactive-tmux:skills-test lib/agentic-primitives/providers/workspaces/interactive-tmux/
```

Expected: both builds succeed.

- [ ] **Step 3: Verify the pinned CLI's agent keys** (validates Task 9's `_SKILLS_CLI_AGENT_KEYS` table):

```bash
docker run --rm agentic-workspace-claude-cli:skills-test skills --version
docker run --rm agentic-workspace-claude-cli:skills-test sh -c "skills add --help"
```

Expected: version `1.5.14`; help output lists agent identifiers. Confirm `claude-code`, `codex`, and the gemini key. IF the gemini key differs from `gemini-cli`, fix `_SKILLS_CLI_AGENT_KEYS` in Task 9's code now and note it in the commit message.

- [ ] **Step 4: Smoke-test an offline local-path install inside the image:**

```bash
docker run --rm agentic-workspace-claude-cli:skills-test sh -c '
  mkdir -p /tmp/s/demo && printf -- "---\nname: demo\ndescription: d\n---\nbody\n" > /tmp/s/demo/SKILL.md &&
  cd /tmp && skills add ./s/demo --agent claude-code -y &&
  ls /tmp/.claude/skills/ || ls ~/.claude/skills/'
```

Expected: exit 0 and the skill folder appears in the claude skills directory (note WHICH directory - project-relative or home - and confirm the agent will discover it given `/workspace` is the agent's cwd; if installs are cwd-relative, Task 9's `execute()` call must pass `working_directory="/workspace"`, so go back and add that if needed).

- [ ] **Step 5: Commit in the submodule, push, bump the pin:**

```bash
cd lib/agentic-primitives
git checkout -b feat/bake-skills-cli && git add -A && git commit -m "feat(workspaces): bake skills CLI 1.5.14 into claude-cli and interactive-tmux images"
git push -u origin feat/bake-skills-cli
# open PR in agentic-primitives per its process; after merge, from the syn137 worktree:
cd ../.. && git add lib/agentic-primitives && git commit -m "chore: bump agentic-primitives for baked skills CLI (#772)"
```

(If the submodule PR round-trip blocks the session, keep the submodule on the feature branch locally and flag it in the PR description - do NOT pin syn137 to an unmerged submodule sha in the final PR.)

---

### Task 11: End-to-end integration test

**Files:**
- Create: test alongside the existing execute_workflow integration tests (find the pattern with `grep -rln "run_setup_phase" --include="test_*.py" packages/ apps/` and pick the file that fakes `ManagedWorkspace` end-to-end)

**Interfaces:** consumes the whole pipeline.

- [ ] **Step 1:** Write a test that: registers one skill through `RegisterSkillHandler` (in-memory storage), builds a workflow definition YAML string with a phase-scoped `skills:` entry and `agent_id: codex`, seeds it, resolves it, runs `WorkspaceProvisionHandler.handle` against the fake workspace, and asserts (a) `inject_files` received `(".syn-skills/<name>/SKILL.md", ...)` and (b) `execute` received the `skills add ... --agent codex -y` command.
- [ ] **Step 2:** Run it - PASS.
- [ ] **Step 3:** Full gate: `just fitness-check && uv run ruff check . && uv run ruff format --check . && uv run pytest packages/syn-domain apps/syn-api -q`. Expected: all green.
- [ ] **Step 4: Commit** - `git commit -am "test(skills): end-to-end registration-to-install integration test (#772)"`

---

### Task 12: Update issue #772 and open the PR

- [ ] **Step 1:** `just docs-sync` and `just codegen` one final time; commit any regenerated files.
- [ ] **Step 2:** Push the branch (`git push -u origin feat/772-skills-injection`) and open a PR to `main` titled `feat: harness-agnostic skill injection, plan 1 of 3 (#772)`, body linking issue #772 and stating what Plans 2-3 will cover. Do NOT merge - the user merges manually after a review pass.
- [ ] **Step 3:** Comment on issue #772 with the PR link and the Plan 1/2/3 breakdown.

---

## Self-Review Notes (performed while writing)

- **Spec coverage:** spec sections 1 (two-layer: platform plugins untouched - satisfied by additive approach), 2 (YAML: Tasks 1, 5), 3 (domain/storage: Tasks 2-4, 7), 4 (provisioning: Tasks 8-9, incl. fail-fast fix), 5 (images: Task 10), 8 (testing: per-task tests + Task 11). Spec sections 6 (CLI) and 7 (docs/ADR) are explicitly Plan 2/3 - hard cutover (removal) is Plan 3.
- **Type consistency:** `SkillRef.skill_name` / `ResolvedSkill.skill_name` used consistently; `expand_skill_entry` returns `list[SkillRef]`; handler signature `handle(source_url, version, skill_name, files)` (no manifest arg - unlike plugins, frontmatter is always derived from the tree, one less drift surface).
- **Known risk called out in-plan:** the `_SKILLS_CLI_AGENT_KEYS` values and the install directory semantics (cwd-relative vs home) are verified empirically in Task 10 steps 3-4, with explicit instructions to adjust Task 9 if reality differs.
