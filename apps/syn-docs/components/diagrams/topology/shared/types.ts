// Source: APS VIZ01 substandard - https://github.com/AgentParadise/agent-paradise-standards-system
// Copy of: standards-experimental/v1/EXP-V1-0001-code-topology/substandards/VIZ01-dashboard/src/react/shared/types.ts

/** A single dependency edge from dependencies.json */
export interface DependencyEdge {
  from: string;
  to: string;
  weight: number;
}

/** A single module entry from modules.json */
export interface ModuleMetric {
  id: string;
  metrics: {
    lines_of_code: number;
    function_count: number;
    avg_cyclomatic: number;
    martin?: {
      instability?: number;
      abstractness?: number;
    };
  };
}

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
