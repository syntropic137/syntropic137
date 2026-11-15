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
