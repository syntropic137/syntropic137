// Source: APS VIZ01 substandard - https://github.com/AgentParadise/agent-paradise-standards-system
// Copy of: standards-experimental/v1/EXP-V1-0001-code-topology/substandards/VIZ01-dashboard/src/react/shared/filters.ts

import type { DependencyEdge, ModuleMetric, TopoNode, TopoLink } from './types';
import { getContextColor } from './colors';

function shortName(id: string): string {
  const parts = id.replace(/::/g, '.').split('.');
  return parts[parts.length - 1] || id;
}

const CONTEXT_KEYWORDS = [
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
] as const;

function inferContext(id: string): string {
  const lower = id.toLowerCase();
  for (const c of CONTEXT_KEYWORDS) {
    if (lower.includes(c)) return c;
  }
  return 'other';
}

export interface FilterOptions {
  excludePrefixes?: string[];
  minLoc?: number;
  colorOverrides?: Record<string, string>;
}

function filterModules(
  modules: ModuleMetric[],
  excludePrefixes: string[],
  minLoc: number,
): Map<string, ModuleMetric> {
  const moduleMap = new Map<string, ModuleMetric>();
  for (const m of modules) {
    if (excludePrefixes.some((p) => m.id.startsWith(p))) continue;
    if (m.metrics.lines_of_code < minLoc) continue;
    moduleMap.set(m.id, m);
  }
  return moduleMap;
}

function toTopoNode(id: string, m: ModuleMetric, colorOverrides?: Record<string, string>): TopoNode {
  return {
    id,
    name: shortName(id),
    loc: m.metrics.lines_of_code,
    color: getContextColor(id, colorOverrides),
    context: inferContext(id),
    functionCount: m.metrics.function_count,
    avgCyclomatic: m.metrics.avg_cyclomatic,
    instability: m.metrics.martin?.instability ?? 0.5,
  };
}

export function buildTopologyGraph(
  modules: ModuleMetric[],
  edges: DependencyEdge[],
  options: FilterOptions = {},
): { nodes: TopoNode[]; links: TopoLink[] } {
  const {
    excludePrefixes = ['worktrees.', 'worktrees::'],
    minLoc = 100,
    colorOverrides,
  } = options;

  const moduleMap = filterModules(modules, excludePrefixes, minLoc);

  const nodes: TopoNode[] = [];
  const nodeIds = new Set<string>();
  for (const [id, m] of moduleMap) {
    nodeIds.add(id);
    nodes.push(toTopoNode(id, m, colorOverrides));
  }

  const links: TopoLink[] = [];
  for (const e of edges) {
    if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
      links.push({ source: e.from, target: e.to, weight: e.weight });
    }
  }

  return { nodes, links };
}
