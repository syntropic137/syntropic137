"""Fixtures shared by the code-quality fitness functions."""

from __future__ import annotations

import pytest
from ci.fitness.code_quality._syn_ui import Facts, Graph, generate_facts


@pytest.fixture(scope="session")
def syn_ui_graph(tmp_path_factory: pytest.TempPathFactory) -> Graph:
    """The syn-ui sources and planted trees, parsed once per session (ADR-074 checks)."""
    facts: Facts = generate_facts(tmp_path_factory.mktemp("syn_ui") / "boundary-facts.json")
    return Graph(facts)
