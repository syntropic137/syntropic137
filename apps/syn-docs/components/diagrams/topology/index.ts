'use client';

import dynamic from 'next/dynamic';

export const TopologyDependencyGraph = dynamic(
  () =>
    import('./TopologyDependencyGraph').then((m) => ({
      default: m.TopologyDependencyGraph,
    })),
  { ssr: false },
);
