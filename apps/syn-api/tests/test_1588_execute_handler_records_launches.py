"""Production builds ExecuteWorkflowHandler with ``launches=`` (#1588).

The argument is optional so domain fixtures stay cheap. Unwired, launches are
never recorded on the template's stream, and archive is back to trusting a
read model that cannot see an execution that started a moment ago.
"""

from __future__ import annotations

import ast
from pathlib import Path

import syn_api._wiring as wiring


def test_the_composition_root_passes_launches() -> None:
    tree = ast.parse(Path(wiring.__file__).read_text(encoding="utf-8"))
    constructions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ExecuteWorkflowHandler"
    ]
    assert constructions, "_wiring no longer constructs ExecuteWorkflowHandler; this check is blind"
    for call in constructions:
        assert any(kw.arg == "launches" for kw in call.keywords)
