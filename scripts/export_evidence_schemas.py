#!/usr/bin/env python3
"""Write the evidence contract's JSON Schemas to schemas/evidence/.

The models in `syn_domain.contexts.orchestration._shared.evidence_contract`
are the source of truth (ADR-014 §10). The unit test beside them fails when a
checked-in schema differs from what this script would write.

Usage:
    uv run python scripts/export_evidence_schemas.py          # write
    uv run python scripts/export_evidence_schemas.py --check  # exit 1 on drift
"""

from __future__ import annotations

import sys
from pathlib import Path

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    SCHEMA_FILES,
    render_schema,
)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "evidence"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale: list[str] = []
    for name, model in SCHEMA_FILES:
        path = SCHEMA_DIR / name
        text = render_schema(model)
        if check:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if stale:
        print(f"Stale evidence schemas: {stale}. Run: uv run python {Path(__file__).name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
