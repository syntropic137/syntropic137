'use client';

// Source: APS VIZ01 substandard - https://github.com/AgentParadise/agent-paradise-standards-system

import dynamic from 'next/dynamic';

export const TopologyDependencyGraph = dynamic(
  () =>
    import('./TopologyDependencyGraph').then((m) => ({
      default: m.TopologyDependencyGraph,
    })),
  { ssr: false },
);

export type { TopologyDependencyGraphProps } from './TopologyDependencyGraph';
