"""PyYAML reference parse of every workflow YAML under workflows/ (#1618).

The CLI parses a workflow package and uploads the result; the server parses
YAML with PyYAML ``safe_load``. If the two ever read the same file differently
the install is silently wrong, which is how sdlc/implement-v3 went in as four
phases instead of ten. This script writes what PyYAML reads, and two tests hold
both sides to it:

- ``scripts/tests/test_workflow_yaml_reference.py`` - the fixture is still what
  PyYAML reads, and the server stores every phase of it.
- ``apps/syn-cli-node/tests/packages/workflow-yaml-reference.test.ts`` - the
  CLI's loader reads the same thing.

Regenerate after editing any workflow YAML:

    uv run python scripts/workflow_yaml_reference.py --write
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / "workflows"
FIXTURE = REPO_ROOT / "apps/syn-cli-node/tests/fixtures/workflow-yaml-reference.json"


class PhaseReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str | None
    order: int | None
    model: str | None
    prompt_file: str | None


class FileReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    phases: list[PhaseReference]
    document_sha256: str
    """sha256 of the canonical JSON of the whole parsed document."""


class Reference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    files: dict[str, FileReference]
    """Keyed by path relative to the repo root."""


def canonical_json(value: object) -> str:
    """Must match ``canonicalJson`` in the CLI test byte for byte."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _optional(value: object, kind: type) -> object:
    return value if isinstance(value, kind) and not isinstance(value, bool) else None


def reference_for(path: Path) -> FileReference:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_phases = document.get("phases") if isinstance(document, dict) else None
    phases = [
        PhaseReference(
            id=_optional(p.get("id"), str),  # type: ignore[arg-type]
            order=_optional(p.get("order"), int),  # type: ignore[arg-type]
            model=_optional(p.get("model"), str),  # type: ignore[arg-type]
            prompt_file=_optional(p.get("prompt_file"), str),  # type: ignore[arg-type]
        )
        for p in (raw_phases if isinstance(raw_phases, list) else [])
        if isinstance(p, dict)
    ]
    digest = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
    return FileReference(phases=phases, document_sha256=digest)


def workflow_yaml_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS_DIR.rglob("*.y*ml") if p.suffix in {".yaml", ".yml"})


def build_reference() -> Reference:
    return Reference(
        files={p.relative_to(REPO_ROOT).as_posix(): reference_for(p) for p in workflow_yaml_files()}
    )


def render(reference: Reference) -> str:
    return json.dumps(reference.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite the fixture")
    args = parser.parse_args()
    rendered = render(build_reference())
    if args.write:
        FIXTURE.write_text(rendered, encoding="utf-8")
        print(f"wrote {FIXTURE.relative_to(REPO_ROOT)}")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
