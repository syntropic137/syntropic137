'use client';

import { useMemo } from 'react';
import depData from '../../../../../../.topology/graphs/dependencies.json';
import modData from '../../../../../../.topology/metrics/modules.json';
import { getContextColor } from './colors';

export interface TopoNode {
  id: string;
  name: string;
  loc: number;
  color: string;
  context: string;
  functionCount: number;
  avgCyclomatic: number;
  instability: number;
}

export interface TopoLink {
  source: string;
  target: string;
  weight: number;
}

function shortName(id: string): string {
  const parts = id.replace(/::/g, '.').split('.');
  return parts[parts.length - 1] || id;
}

function inferContext(id: string): string {
  const lower = id.toLowerCase();
  const contexts = [
    'event-sourcing-platform',
    'agentic-primitives',
    'orchestration',
    'observability',
    'workspace',
    'workflow',
    'session',
    'artifact',
    'github',
    'cost',
    'token',
  ];
  for (const c of contexts) {
    if (lower.includes(c)) return c;
  }
  return 'other';
}

export function useTopologyData() {
  return useMemo(() => {
    // Build module map, filtering worktrees and < 100 LOC
    const moduleMap = new Map<string, (typeof modData.modules)[number]>();
    for (const m of modData.modules) {
      if (m.id.startsWith('worktrees.') || m.id.startsWith('worktrees::')) continue;
      if (m.metrics.lines_of_code < 100) continue;
      moduleMap.set(m.id, m);
    }

    const nodes: TopoNode[] = [];
    const nodeIds = new Set<string>();
    for (const [id, m] of moduleMap) {
      nodeIds.add(id);
      nodes.push({
        id,
        name: shortName(id),
        loc: m.metrics.lines_of_code,
        color: getContextColor(id),
        context: inferContext(id),
        functionCount: m.metrics.function_count,
        avgCyclomatic: m.metrics.avg_cyclomatic,
        instability: m.metrics.martin?.instability ?? 0.5,
      });
    }

    const links: TopoLink[] = [];
    for (const e of depData.edges) {
      if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
        links.push({ source: e.from, target: e.to, weight: e.weight });
      }
    }

    return { nodes, links };
  }, []);
}
