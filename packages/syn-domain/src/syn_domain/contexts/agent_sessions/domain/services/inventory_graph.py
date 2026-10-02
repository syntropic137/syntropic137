"""Iterative graph checks without harness knowledge or recursion limits."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import EvidenceClass

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import LineageEdge

_VERIFIED = frozenset({EvidenceClass.REGISTERED, EvidenceClass.CORROBORATED})
Vertex = tuple[str, str | None]
EdgeEndpoints = tuple[Vertex, Vertex]
Adjacency = dict[Vertex, set[Vertex]]


def edge_endpoints(edge: LineageEdge) -> EdgeEndpoints:
    """Resumed segments share native identity, but are distinct graph vertices."""
    return ((edge.parent.key, edge.parent_segment), (edge.child.key, edge.child_segment))


def _vertex_order(vertex: Vertex) -> tuple[str, str]:
    return vertex[0], vertex[1] or ""


def _finish_order(forward: Adjacency, vertices: set[Vertex]) -> list[Vertex]:
    seen: set[Vertex] = set()
    order: list[Vertex] = []
    for root in sorted(vertices, key=_vertex_order):
        stack = [(root, False)]
        while stack:
            node, finished = stack.pop()
            if finished:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend(
                    (child, False) for child in sorted(forward.get(node, ()), key=_vertex_order)
                )
    return order


def _components(reverse: Adjacency, order: list[Vertex]) -> Iterator[set[Vertex]]:
    seen: set[Vertex] = set()
    for root in reversed(order):
        if root in seen:
            continue
        component: set[Vertex] = set()
        pending = [root]
        while pending:
            node = pending.pop()
            if node in seen:
                continue
            seen.add(node)
            component.add(node)
            pending.extend(reverse.get(node, ()))
        yield component


def cyclic_edges(edges: Sequence[LineageEdge]) -> frozenset[EdgeEndpoints]:
    """Return cycle participants, not downstream descendants (Kosaraju)."""
    forward: Adjacency = defaultdict(set)
    reverse: Adjacency = defaultdict(set)
    for edge in edges:
        if edge.confidence in _VERIFIED:
            parent, child = edge_endpoints(edge)
            forward[parent].add(child)
            reverse[child].add(parent)
    order = _finish_order(forward, set(forward) | set(reverse))
    cycles: set[EdgeEndpoints] = set()
    for component in _components(reverse, order):
        # A singleton contributes only a self-loop; multi-vertex components
        # contribute only internal edges. Bridges are never included.
        cycles.update(
            (parent, child)
            for parent in component
            for child in forward.get(parent, ())
            if child in component
        )
    return frozenset(cycles)
