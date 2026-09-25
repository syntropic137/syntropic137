"""Fitness function: harness formats stay in adapters; inference has one owner (#1398).

AGENTS.md: "If it changes when Anthropic or OpenAI ships a new CLI version, it
belongs in agentic-primitives." Syntropic137 depends on a port, not a format:
native transcripts are normalized by the agentic-primitives evidence readers,
reached ONLY through ``syn_adapters.session_inventory.native_evidence``, and
relationships are inferred ONLY by the agent_sessions domain services behind
the reconcile slice.

Four rules, each zero-tolerance for new code:

1. Vendor transcript parsing: no vendor-format record keys or format literals
   in the API, the clients (CLI + dashboard) or the agent_sessions context.
2. Harness-format imports: no ``agentic_isolation`` / vendor stream modules in
   the API, the agent_sessions context or the inventory replication modules.
3. Domain-service purity: the inventory domain services (including
   ``session_relationship_resolver``) import no adapters or I/O libraries.
4. Single inference owner: only the reconcile slice (and the services
   themselves) may depend on the domain services; replication, API and client
   modules never re-run or duplicate inference. The resolver, inventory
   slices, inventory API route and replication modules also carry no
   harness-name literal, so they cannot branch on a harness.

Pre-existing violations are exact-count exemptions in fitness_exceptions.toml
``[harness_format_boundary]``; an exemption whose count drops is stale and fails
so the budget can only ratchet down.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from ci.fitness._imports import all_imports
from ci.fitness.conftest import load_exceptions, repo_root

if TYPE_CHECKING:
    from pathlib import Path

_AGENT_SESSIONS = "packages/syn-domain/src/syn_domain/contexts/agent_sessions"
_SERVICES = f"{_AGENT_SESSIONS}/domain/services"
_RECONCILE_SLICE = f"{_AGENT_SESSIONS}/slices/reconcile_session_inventory"
_API = "apps/syn-api/src/syn_api"
_INVENTORY_ADAPTERS = "packages/syn-adapters/src/syn_adapters/session_inventory"
_CLIENT_ROOTS = ("apps/syn-cli-node/src", "apps/syn-dashboard-ui/src")

#: Record keys and format identifiers that only a vendor transcript/stream
#: parser needs. Matched as an EXACT string constant (Python) or an exact quoted
#: literal (TypeScript), so prose and docstrings never match.
VENDOR_FORMAT_MARKERS = frozenset(
    {
        # codex rollout / exec stream
        "session_meta",
        "response_item",
        "event_msg",
        "turn_context",
        "thread_spawn",
        "forked_from_id",
        "parent_thread_id",
        "item.started",
        "item.completed",
        "turn.completed",
        "codex-rollout-jsonl",
        # claude code transcript
        "toolUseResult",
        "isSidechain",
        "sessionId",
        "agentId",
        "claude-code-jsonl",
    }
)

#: Modules that ARE harness-format knowledge. Only adapters may import them.
HARNESS_FORMAT_MODULES = (
    "agentic_isolation",
    "claude_agent_sdk",
    "syn_shared.codex_stream",
)

#: What a pure domain service may never reach for.
DOMAIN_SERVICE_FORBIDDEN = (
    "syn_adapters",
    "syn_api",
    "agentic_isolation",
    "agentic_events",
    "claude_agent_sdk",
    "asyncpg",
    "fastapi",
    "httpx",
    "redis",
    "minio",
    "aioboto3",
    "boto3",
    "docker",
)

#: Inference entry points. Importing any of these outside the owner duplicates it.
INFERENCE_MODULE = "syn_domain.contexts.agent_sessions.domain.services"

HARNESS_NAMES = frozenset({"claude", "codex", "gemini", "claude-code", "claude_code", "openai"})


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    lineno: int
    detail: str

    def render(self) -> str:
        return f"[{self.rule}] {self.path}:{self.lineno}: {self.detail}"


def _py_files(root: Path, rel: str) -> list[Path]:
    base = root / rel
    if base.is_file():
        return [base]
    return sorted(
        p
        for p in base.rglob("*.py")
        if not p.name.startswith("test_") and "tests" not in p.relative_to(root).parts
    )


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _string_constants(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _matches(module: str, prefixes: tuple[str, ...] | str) -> bool:
    options = (prefixes,) if isinstance(prefixes, str) else prefixes
    return any(module == p or module.startswith(p + ".") for p in options)


def _vendor_parsing_python(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for rel in (_API, _AGENT_SESSIONS):
        for path in _py_files(root, rel):
            for lineno, value in _string_constants(path):
                if value in VENDOR_FORMAT_MARKERS:
                    found.append(Violation("vendor-parsing", _rel(root, path), lineno, repr(value)))
    return found


def _client_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in _CLIENT_ROOTS:
        for path in sorted((root / rel).rglob("*.ts*")):
            parts = path.relative_to(root).parts
            if "generated" in parts or "__tests__" in parts or ".test." in path.name:
                continue
            files.append(path)
    return files


_TS_LITERAL = re.compile(r"""(['"`])([^'"`\n]{1,64})\1""")


def _vendor_parsing_clients(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for path in _client_files(root):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _TS_LITERAL.finditer(line):
                if match.group(2) in VENDOR_FORMAT_MARKERS:
                    found.append(
                        Violation("vendor-parsing", _rel(root, path), lineno, match.group(0))
                    )
    return found


def _harness_format_imports(root: Path) -> list[Violation]:
    found: list[Violation] = []
    replication = [
        p
        for p in _py_files(root, _INVENTORY_ADAPTERS)
        if p.name.startswith(("replication_", "exporter_", "capture_delivery_"))
    ]
    targets = [*_py_files(root, _API), *_py_files(root, _AGENT_SESSIONS), *replication]
    for path in targets:
        for imp in all_imports(path):
            if _matches(imp.module, HARNESS_FORMAT_MODULES):
                found.append(
                    Violation("harness-format-import", _rel(root, path), imp.lineno, imp.module)
                )
    return found


def _domain_service_purity(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for path in _py_files(root, _SERVICES):
        for imp in all_imports(path):
            if _matches(imp.module, DOMAIN_SERVICE_FORBIDDEN):
                found.append(
                    Violation("domain-service-adapter", _rel(root, path), imp.lineno, imp.module)
                )
    return found


def _inference_owners(root: Path) -> list[Violation]:
    """Only the reconcile slice and the services themselves may import inference."""
    found: list[Violation] = []
    owners = (f"{_SERVICES}/", f"{_RECONCILE_SLICE}/")
    for rel in ("apps", "packages"):
        for path in sorted((root / rel).glob("*/src/**/*.py")):
            relpath = _rel(root, path)
            if path.name.startswith("test_") or relpath.startswith(owners):
                continue
            for imp in all_imports(path):
                names = set(imp.names)
                if _matches(imp.module, INFERENCE_MODULE) or (
                    imp.module == "syn_domain.contexts.agent_sessions.domain"
                    and "services" in names
                ):
                    found.append(Violation("duplicated-inference", relpath, imp.lineno, imp.module))
    return found


def _harness_neutral_files(root: Path) -> list[Path]:
    slices = (
        "reconcile_session_inventory",
        "replicate_session_inventory",
        "capture_local_transcript",
        "read_local_transcript",
    )
    files = [*_py_files(root, _SERVICES), *_py_files(root, f"{_AGENT_SESSIONS}/ports")]
    for name in slices:
        files.extend(_py_files(root, f"{_AGENT_SESSIONS}/slices/{name}"))
    files.extend(
        p
        for p in _py_files(root, _INVENTORY_ADAPTERS)
        if p.name != "native_evidence.py"  # the one sanctioned harness seam
    )
    for rel in (
        f"{_API}/routes/executions/inventory.py",
        f"{_API}/inventory_types.py",
        f"{_API}/_wiring_inventory.py",
        f"{_API}/services/inventory_lifecycle.py",
    ):
        files.extend(_py_files(root, rel))
    return files


def _harness_branches(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for path in _harness_neutral_files(root):
        for lineno, value in _string_constants(path):
            if value.lower() in HARNESS_NAMES:
                found.append(Violation("harness-branch", _rel(root, path), lineno, repr(value)))
    return found


def collect_violations(root: Path) -> list[Violation]:
    return [
        *_vendor_parsing_python(root),
        *_vendor_parsing_clients(root),
        *_harness_format_imports(root),
        *_domain_service_purity(root),
        *_inference_owners(root),
        *_harness_branches(root),
    ]


def _budgets(root: Path) -> dict[str, int]:
    section = load_exceptions(root).get("harness_format_boundary", {})
    budgets: dict[str, int] = {}
    for path, entry in section.items():
        assert isinstance(entry, dict), f"{path}: exemption must be an inline table"
        issue = entry.get("issue")
        assert isinstance(issue, str) and re.fullmatch(r"#\d+", issue), (
            f"{path}: exemption needs issue = '#NNN'"
        )
        count = entry.get("violations")
        assert isinstance(count, int) and count > 0, f"{path}: violations must be > 0"
        budgets[path] = count
    return budgets


def evaluate(root: Path, budgets: dict[str, int]) -> list[str]:
    """Return failure messages: unexempted violations, over-budget or stale exemptions."""
    by_path: dict[str, list[Violation]] = {}
    for violation in collect_violations(root):
        by_path.setdefault(violation.path, []).append(violation)
    failures: list[str] = []
    for path, items in sorted(by_path.items()):
        allowed = budgets.get(path, 0)
        if len(items) > allowed:
            failures.extend(item.render() for item in items)
            if allowed:
                failures.append(f"{path}: {len(items)} violations exceed exemption of {allowed}")
    for path, allowed in sorted(budgets.items()):
        actual = len(by_path.get(path, []))
        if actual < allowed:
            failures.append(
                f"{path}: exemption allows {allowed} but only {actual} remain; "
                "lower the budget (delete it at 0) in fitness_exceptions.toml"
            )
    return failures


@pytest.mark.architecture
def test_harness_formats_stay_in_adapters_and_inference_has_one_owner() -> None:
    root = repo_root()
    failures = evaluate(root, _budgets(root))
    if failures:
        pytest.fail(
            "Harness-format boundary violated (#1398). Vendor transcript parsing and "
            "harness-format imports belong in agentic-primitives behind "
            "syn_adapters.session_inventory.native_evidence; relationship inference "
            "belongs only to agent_sessions domain services via the reconcile slice.\n  "
            + "\n  ".join(failures)
        )


# ---------------------------------------------------------------------------
# The check must be able to fail: plant each violation class in a copy of the
# real tree and assert both that the mutation applied and that it is caught.
# ---------------------------------------------------------------------------

_RESOLVER = f"{_SERVICES}/session_relationship_resolver.py"
_REPLICATION_WORKER = f"{_INVENTORY_ADAPTERS}/replication_worker.py"
_INVENTORY_ROUTE = f"{_API}/routes/executions/inventory.py"
_CLIENT_FILE = "apps/syn-cli-node/src/commands/execution-sessions.ts"


def _copy_tree(root: Path, dest: Path) -> None:
    for rel in (_API, _AGENT_SESSIONS, _INVENTORY_ADAPTERS, *_CLIENT_ROOTS):
        shutil.copytree(
            root / rel,
            dest / rel,
            ignore=shutil.ignore_patterns("node_modules", "__pycache__", "dist", "generated"),
        )


def _plant(path: Path, snippet: str) -> None:
    before = path.read_text(encoding="utf-8")
    assert snippet not in before, "planted snippet already present; mutation would be vacuous"
    path.write_text(before + snippet, encoding="utf-8")
    assert snippet in path.read_text(encoding="utf-8"), "mutation did not apply"


_MUTATIONS: dict[str, tuple[str, str, str]] = {
    "vendor-parsing-resolver": (
        _RESOLVER,
        '\n\ndef _planted(row: dict[str, object]) -> object:\n    return row.get("isSidechain")\n',
        "vendor-parsing",
    ),
    "vendor-parsing-api": (
        _INVENTORY_ROUTE,
        '\n\n_PLANTED = "session_meta"\n',
        "vendor-parsing",
    ),
    "vendor-parsing-client": (
        _CLIENT_FILE,
        "\nconst planted = (row: { type?: string }) => row.type === 'response_item'\n",
        "vendor-parsing",
    ),
    "harness-import-api": (
        _INVENTORY_ROUTE,
        "\n\nfrom agentic_isolation.harnesses.claude.evidence import ClaudeNativeEvidenceReader\n",
        "harness-format-import",
    ),
    "adapter-in-domain-service": (
        _RESOLVER,
        "\n\ndef _planted() -> None:\n"
        "    from syn_adapters.session_inventory.database import SessionInventoryDatabase\n",
        "domain-service-adapter",
    ),
    "resolver-in-replication": (
        _REPLICATION_WORKER,
        "\n\nfrom syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver"
        " import resolve_relationships\n",
        "duplicated-inference",
    ),
    "harness-branch-resolver": (
        _RESOLVER,
        '\n\ndef _planted(harness: str) -> bool:\n    return harness == "codex"\n',
        "harness-branch",
    ),
}


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(_MUTATIONS))
def test_planted_violation_is_caught(name: str, tmp_path: Path) -> None:
    root = repo_root()
    rel, snippet, rule = _MUTATIONS[name]
    _copy_tree(root, tmp_path)
    budgets = _budgets(root)
    assert evaluate(tmp_path, budgets) == [], "unmutated copy must pass"
    _plant(tmp_path / rel, snippet)
    failures = evaluate(tmp_path, budgets)
    assert any(f.startswith(f"[{rule}] {rel}:") for f in failures), failures


@pytest.mark.architecture
def test_exemption_is_exact_and_ratchets(tmp_path: Path) -> None:
    root = repo_root()
    _copy_tree(root, tmp_path)
    budgets = _budgets(root)
    exempt = f"{_AGENT_SESSIONS}/transcript_usage.py"
    assert exempt in budgets, "transcript_usage.py exemption (#1284) expected"
    # One more marker in the exempt file exceeds its exact budget.
    _plant(tmp_path / exempt, '\n\n_PLANTED = "session_meta"\n')
    assert any("exceed exemption" in f for f in evaluate(tmp_path, budgets))
    # A budget above the real count is stale and must be lowered.
    stale = {**budgets, exempt: budgets[exempt] + 5}
    assert any("lower the budget" in f for f in evaluate(root, stale))
