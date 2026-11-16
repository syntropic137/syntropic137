"""architecture_manifest.py: the docs generator, fed the reader's manifest,
must see what it would have seen from `vsa manifest` (#1782).

The fixture tree is a repo in miniature. Every file in it tests a discovery
rule, and each rule has a twin the reader must skip. A reader that ignored
those rules would get different counts, a different context set or a missing
subscription.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from architecture_manifest import (
    ArchitectureManifest,
    UnsupportedLayoutError,
    read_manifest,
    subscribed_events,
)

pytestmark = pytest.mark.unit

GENERATOR = Path(__file__).resolve().parents[1] / "generate-architecture-docs.py"

VSA_YAML = """\
version: 1
root: ./src/contexts
language: python
domain:
  path: domain
  commands:
    path: "commands"
  events:
    path: "events"
"""

PROJECTION = """\
class InvoiceListProjection(CheckpointedProjection):
    async def on_invoice_issued(self, event_data: dict) -> None: ...
    def get_by_id(self, invoice_id: str) -> None: ...
"""

README = """\
The system is organized into 1 bounded contexts following VSA:

| Context | Aggregates | Purpose |
|---------|------------|---------|
| **`billing`** | - | Invoices |
| **`reporting`** | - | Reports |

| CQRS | Commands (0) → Events (0) → Projections (0) |
"""


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def make_repo(root: Path) -> Path:
    """The fixture tree; the parity check runs `vsa` on it too."""
    ctx = "src/contexts"
    _write(
        root,
        {
            "vsa.yaml": VSA_YAML,
            "README.md": README,
            f"{ctx}/billing/domain/aggregate_invoice/InvoiceAggregate.py": "",
            f"{ctx}/billing/domain/aggregate_invoice/test_InvoiceAggregate.py": "",
            f"{ctx}/billing/domain/commands/IssueInvoiceCommand.py": "",
            f"{ctx}/billing/domain/commands/README.md": "",
            f"{ctx}/billing/domain/events/InvoiceIssuedEvent.py": "",
            f"{ctx}/billing/domain/events/InvoiceIssuedEvent.v2.py": "",
            f"{ctx}/billing/domain/events/_versioned/InvoiceIssuedEvent.v1.py": "",
            f"{ctx}/billing/domain/events/_upcasters/InvoiceIssuedEvent_v1_to_v2.py": "",
            f"{ctx}/billing/slices/list_invoices/projection.py": PROJECTION,
            f"{ctx}/billing/slices/list_invoices/__pycache__/StaleProjection.py": PROJECTION,
            # A context without domain/ is still a context; its projection is
            # never scanned, because vsa only scans contexts with a domain.
            f"{ctx}/reporting/slices/totals/TotalsProjection.py": PROJECTION,
            f"{ctx}/_shared/domain/commands/SharedCommand.py": "",
        },
    )
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def test_reader_finds_one_of_each_in_the_repo_layout(repo: Path) -> None:
    manifest = read_manifest(repo, Path("vsa.yaml"))

    assert [c.name for c in manifest.bounded_contexts] == ["billing", "reporting"]
    domain = manifest.domain
    assert [(a.name, a.context) for a in domain.aggregates] == [("InvoiceAggregate", "billing")]
    assert [(c.name, c.file_path) for c in domain.commands] == [
        ("IssueInvoiceCommand", "src/contexts/billing/domain/commands/IssueInvoiceCommand.py")
    ]
    # Each versioned file, beside the current one or under _versioned/, is
    # another event in vsa's count, under the same name.
    assert [e.name for e in domain.events] == ["InvoiceIssuedEvent"] * 3
    assert [p.name for p in domain.projections] == ["InvoiceListProjection"]
    assert domain.relationships.event_to_projections == {
        "invoice_issued": ("InvoiceListProjection",)
    }


def test_generator_reads_the_readers_manifest(repo: Path) -> None:
    """The consumer, not the object: run the docs generator on the output."""
    manifest = read_manifest(repo, Path("vsa.yaml"))
    (repo / "manifest.json").write_text(manifest.model_dump_json(indent=2))

    subprocess.run(
        [sys.executable, str(GENERATOR), "--manifest", "manifest.json", "--out-root", "."],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    readme = (repo / "README.md").read_text()
    assert "| CQRS | Commands (1) → Events (3) → Projections (1) |" in readme
    assert "| **`billing`** | Invoice | Invoices |" in readme
    assert "organized into 2 bounded contexts" in readme
    subscriptions = (repo / "docs/architecture/projection-subscriptions.md").read_text()
    assert "| invoice_issued | InvoiceListProjection | 1 |" in subscriptions


def test_command_order_is_the_order_the_generator_canonicalises_to(repo: Path) -> None:
    """The event-flow table credits the first command whose name prefixes the
    event, in the generator's canonical order, so the reader must agree on it."""
    for context, name in [("zeta", "ACommand"), ("alpha", "ZCommand"), ("alpha", "MCommand")]:
        _write(repo, {f"src/contexts/{context}/domain/commands/{name}.py": ""})
    manifest = read_manifest(repo, Path("vsa.yaml"))

    generator_order = sorted(
        json.loads(manifest.model_dump_json())["domain"]["commands"],
        key=lambda item: json.dumps(item, sort_keys=True),
    )
    assert [c.name for c in manifest.domain.commands] == [c["name"] for c in generator_order]
    assert [c.name for c in manifest.domain.commands] == [
        "MCommand", "ZCommand", "IssueInvoiceCommand", "ACommand"
    ]  # fmt: skip


def test_vsa_manifest_reads_as_the_same_model() -> None:
    """The parity check parses `vsa manifest` output with these models."""
    vsa_output = {
        "version": "0.18.0",
        "bounded_contexts": [{"name": "billing", "path": "./x", "features": []}],
        "domain": {
            "aggregates": [{"name": "InvoiceAggregate", "context": "billing", "line_count": 3}],
            "commands": [
                {
                    "name": "IssueInvoiceCommand",
                    "context": "billing",
                    "file_path": "./src/contexts/billing/domain/commands/IssueInvoiceCommand.py",
                    "has_aggregate_id": False,
                    "fields": [],
                }
            ],
            "events": [],
            "queries": [],
            "upcasters": [],
            "relationships": {"command_to_aggregate": {}},
        },
    }
    manifest = ArchitectureManifest.model_validate(vsa_output).canonical()
    assert manifest.domain.commands[0].file_path == (
        "src/contexts/billing/domain/commands/IssueInvoiceCommand.py"
    )
    assert manifest.domain.projections == ()
    assert manifest.domain.relationships.event_to_projections == {}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("async def on_session_started(self, e): ...", ("session_started",)),
        ("def on_WorkflowCreated(self, e): ...", ("WorkflowCreatedEvent",)),
        ("def handle_WorkflowCreatedEvent(self, e): ...", ("WorkflowCreatedEvent",)),
        ("@Handles(OrderPlacedEvent)\nasync def x(): ...", ("OrderPlacedEvent",)),
        ("handle(event: OrderPlacedEvent)", ("OrderPlacedEvent",)),
        ('subscribed_events = ["a_b", "XEvent", "single"]', ("XEvent",)),
        ("def on_get_by_id(self): ...\ndef on_Start(self): ...\ndef on_a_b(self): ...", ()),
    ],
)
def test_subscribed_events_follow_the_vsa_projection_patterns(
    source: str, expected: tuple[str, ...]
) -> None:
    assert subscribed_events(source) == expected


def test_snake_case_filename_convention_is_refused(repo: Path) -> None:
    (repo / "vsa.yaml").write_text(VSA_YAML + "patterns:\n  filename_convention: snake_case\n")
    with pytest.raises(UnsupportedLayoutError, match="filename_convention"):
        read_manifest(repo, Path("vsa.yaml"))


def test_two_aggregate_roots_in_one_folder_are_refused(repo: Path) -> None:
    _write(repo, {"src/contexts/billing/domain/aggregate_invoice/OtherAggregate.py": ""})
    with pytest.raises(UnsupportedLayoutError, match="more than one aggregate root"):
        read_manifest(repo, Path("vsa.yaml"))


# Divergences from vsa found by independent review of #2292. Each tree below
# is also run through `vsa manifest` by the parity fitness test, so the vsa side
# is checked by vsa itself, not by this file's reading of its source.


def make_disabled_versioning_repo(root: Path) -> Path:
    """event_scanner.rs excludes `_versioned/` from the main scan whether or not
    versioning is enabled; only the separate versioned scan depends on it."""
    make_repo(root)
    (root / "vsa.yaml").write_text(
        VSA_YAML.replace(
            '    path: "events"\n', '    path: "events"\n    versioning:\n      enabled: false\n'
        )
    )
    return root


def make_nested_domain_repo(root: Path) -> Path:
    """domain_scanner.rs scans projections under `domain_path.parent()`: with
    `domain/model`, a projection in the context's `slices/` is out of scope."""
    ctx = "src/contexts"
    _write(
        root,
        {
            "vsa.yaml": VSA_YAML.replace("  path: domain\n", "  path: domain/model\n"),
            f"{ctx}/billing/domain/model/commands/IssueInvoiceCommand.py": "",
            f"{ctx}/billing/slices/list_invoices/projection.py": PROJECTION,
            f"{ctx}/billing/domain/InvoiceListProjection.py": PROJECTION,
        },
    )
    return root


def make_symlinked_context_repo(root: Path) -> Path:
    """WalkDir's entry type does not follow symlinks (scanner.rs)."""
    make_repo(root)
    (root / "src/contexts/alias").symlink_to(root / "src/contexts/billing")
    return root


MARK = "́"  # COMBINING ACUTE ACCENT: a Rust `\w` character, not a Python `re` one
# Every shape the second review of #2292 reproduced against vsa 0.22.0, one
# projection file each. Class-name cases are `projection.py` (named from the
# class); subscription cases are named files, so each contributes its events.
UNICODE_PROJECTIONS = {
    "class_backtrack/projection.py": f"class FooProjectionX{MARK}ProjectionExtra:\n    pass\n",
    "class_in_comment/projection.py": (
        "class TestProjection:\n    # Former class CaféProjection was renamed.\n    pass\n"
    ),
    "class_in_docstring/projection.py": (
        'class TestProjection:\n    """Replaces class CaféProjection from v1."""\n    pass\n'
    ),
    "prose/projection.py": (
        'class ProseProjection:\n    """Résumé, café, 日本語."""\n    # Crème brûlée.\n    pass\n'
    ),
    "decorator/DecoratorProjection.py": f"@Handles(Cafe{MARK}Event)\ndef apply(self, e): pass\n",
    "typed_event/TypedEventProjection.py": f"# handle(event: Cafe{MARK}Event)\n",
    "typed_arg/TypedArgProjection.py": f"# handle(e{MARK}: OrderPlacedEvent)\n",
    "quoted/QuotedProjection.py": f'subscribed_events = ["Cafe{MARK}Event"]\n',
    "ts_on/TsOnProjection.py": f"# on_Cafe{MARK}Created(event)\n",
    "def_on/DefOnProjection.py": f"def on_Cafe{MARK}Created(self, event): ...\n",
    "mark_before_on/MarkBeforeProjection.py": f"x{MARK}on_OrderShipped(event)\n",
}


def make_unicode_identifiers_repo(root: Path) -> Path:
    """Rust regex `\\w` is Unicode word (marks included); Python `re` `\\w` is not."""
    make_repo(root)
    _write(root, {f"src/contexts/billing/slices/{k}": v for k, v in UNICODE_PROJECTIONS.items()})
    return root


DIVERGENCE_TREES = {
    "disabled_versioning": make_disabled_versioning_repo,
    "nested_domain": make_nested_domain_repo,
    "symlinked_context": make_symlinked_context_repo,
    "unicode_identifiers": make_unicode_identifiers_repo,
}


def test_disabled_versioning_still_excludes_the_versioned_tree(tmp_path: Path) -> None:
    manifest = read_manifest(make_disabled_versioning_repo(tmp_path), Path("vsa.yaml"))
    assert [e.name for e in manifest.domain.events] == ["InvoiceIssuedEvent"] * 2


def test_a_nested_domain_path_scans_projections_under_its_parent(tmp_path: Path) -> None:
    manifest = read_manifest(make_nested_domain_repo(tmp_path), Path("vsa.yaml"))
    assert [p.name for p in manifest.domain.projections] == ["InvoiceListProjection"]
    assert [c.name for c in manifest.domain.commands] == ["IssueInvoiceCommand"]


def test_a_symlinked_context_directory_is_not_a_context(tmp_path: Path) -> None:
    manifest = read_manifest(make_symlinked_context_repo(tmp_path), Path("vsa.yaml"))
    assert [c.name for c in manifest.bounded_contexts] == ["billing", "reporting"]
    assert [a.name for a in manifest.domain.aggregates] == ["InvoiceAggregate"]


def test_unicode_identifiers_read_as_vsa_reads_them(tmp_path: Path) -> None:
    """Pinned from `vsa manifest` 0.22.0 on this tree (the parity fitness test
    re-checks it against vsa wherever vsa is installed). A mark mid-name stays in
    the name; a mark before `on_` is a word character, so Rust `\\b` does not match."""
    manifest = read_manifest(make_unicode_identifiers_repo(tmp_path), Path("vsa.yaml"))
    names = sorted(p.name for p in manifest.domain.projections)
    assert f"FooProjectionX{MARK}Projection" in names
    assert names.count("TestProjection") == 2  # prose about other classes changes nothing
    assert "ProseProjection" in names
    assert dict(manifest.domain.relationships.event_to_projections) == {
        f"Cafe{MARK}CreatedEvent": ("DefOnProjection", "TsOnProjection"),
        f"Cafe{MARK}Event": ("DecoratorProjection", "QuotedProjection", "TypedEventProjection"),
        "OrderPlacedEvent": ("TypedArgProjection",),
        "invoice_issued": ("InvoiceListProjection",),
    }
