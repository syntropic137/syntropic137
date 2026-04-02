'use client';

import dynamic from 'next/dynamic';

// Lazy-loaded diagram components — React Flow only loads on pages that use diagrams
export const SystemArchitectureFlow = dynamic(
  () => import('./SystemArchitectureFlow').then(m => ({ default: m.SystemArchitectureFlow })),
  { ssr: false },
);

export const EventSourcingFlow = dynamic(
  () => import('./EventSourcingFlow').then(m => ({ default: m.EventSourcingFlow })),
  { ssr: false },
);

export const TwoEventTypesFlow = dynamic(
  () => import('./TwoEventTypesFlow').then(m => ({ default: m.TwoEventTypesFlow })),
  { ssr: false },
);

export const CQRSFlow = dynamic(
  () => import('./CQRSFlow').then(m => ({ default: m.CQRSFlow })),
  { ssr: false },
);

export const DomainModelFlow = dynamic(
  () => import('./DomainModelFlow').then(m => ({ default: m.DomainModelFlow })),
  { ssr: false },
);

export const StateMachineFlow = dynamic(
  () => import('./StateMachineFlow').then(m => ({ default: m.StateMachineFlow })),
  { ssr: false },
);

export const DeploymentArchitectureFlow = dynamic(
  () => import('./DeploymentArchitectureFlow').then(m => ({ default: m.DeploymentArchitectureFlow })),
  { ssr: false },
);

export const WorkspaceIsolationFlow = dynamic(
  () => import('./WorkspaceIsolationFlow').then(m => ({ default: m.WorkspaceIsolationFlow })),
  { ssr: false },
);

export const ScalingFlow = dynamic(
  () => import('./ScalingFlow').then(m => ({ default: m.ScalingFlow })),
  { ssr: false },
);

export const PluginEcosystemFlow = dynamic(
  () => import('./PluginEcosystemFlow').then(m => ({ default: m.PluginEcosystemFlow })),
  { ssr: false },
);
