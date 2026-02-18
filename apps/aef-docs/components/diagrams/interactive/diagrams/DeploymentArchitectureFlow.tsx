'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, NODE_WIDTH } from '../layout';

const CX = 350;

// Layer Y positions — more breathing room between layers
const Y_EXT = 0;
const Y_APP = 120;
const Y_DATA = 340;

// External Access — 2 nodes centered
const extPositions = layoutRow(['tunnel', 'webhooks'], Y_EXT + 35, CX, 40);

// Frontend — single node, vertically centered in its group
const frontPos = { x: CX - 260, y: Y_APP + 50 };

// Backend — 3 nodes stacked with proper spacing to fit in group
const backPositions = {
  dashboard: { x: CX + 20, y: Y_APP + 35 },
  collector: { x: CX + 20, y: Y_APP + 95 },
  eventstore: { x: CX + 20, y: Y_APP + 155 },
};

// Data layer — 3 nodes centered
const dataPositions = layoutRow(['pg', 'redis', 'minio'], Y_DATA + 35, CX, 30, NODE_WIDTH.sm);

const nodes: Node[] = [
  // Groups — properly sized to contain their nodes
  {
    id: 'grpExt', type: 'groupNode', position: { x: CX - 260, y: Y_EXT },
    data: { title: 'External Access', color: 'indigo' },
    style: { width: 520, height: 90 },
  },
  {
    id: 'grpFront', type: 'groupNode', position: { x: CX - 280, y: Y_APP },
    data: { title: 'Frontend', color: 'purple' },
    style: { width: 200, height: 120 },
  },
  {
    id: 'grpBack', type: 'groupNode', position: { x: CX - 10, y: Y_APP },
    data: { title: 'Backend', color: 'cyan' },
    style: { width: 230, height: 210 },
  },
  {
    id: 'grpData', type: 'groupNode', position: { x: CX - 280, y: Y_DATA },
    data: { title: 'Data Layer', color: 'emerald' },
    style: { width: 520, height: 90 },
  },

  // External
  { id: 'tunnel', type: 'flowNode', position: extPositions.tunnel, data: { icon: 'globe', label: 'Cloudflare Tunnel', color: 'indigo' } },
  { id: 'webhooks', type: 'flowNode', position: extPositions.webhooks, data: { icon: 'github', label: 'GitHub Webhooks', color: 'indigo' } },

  // Frontend
  { id: 'ui', type: 'flowNode', position: frontPos, data: { icon: 'monitor', label: 'aef-ui', sublabel: 'nginx :80', color: 'purple', size: 'sm' } },

  // Backend
  { id: 'dashboard', type: 'flowNode', position: backPositions.dashboard, data: { icon: 'server', label: 'aef-api', sublabel: 'FastAPI :8000', color: 'cyan', size: 'sm' } },
  { id: 'collector', type: 'flowNode', position: backPositions.collector, data: { icon: 'radio', label: 'event-collector', sublabel: ':8080', color: 'cyan', size: 'sm' } },
  { id: 'eventstore', type: 'flowNode', position: backPositions.eventstore, data: { icon: 'activity', label: 'event-store', sublabel: 'gRPC :50051', color: 'cyan', size: 'sm' } },

  // Data
  { id: 'pg', type: 'flowNode', position: dataPositions.pg, data: { icon: 'database', label: 'TimescaleDB', sublabel: 'PostgreSQL :5432', color: 'emerald', size: 'sm' } },
  { id: 'redis', type: 'flowNode', position: dataPositions.redis, data: { icon: 'zap', label: 'Redis', sublabel: ':6379', color: 'amber', size: 'sm' } },
  { id: 'minio', type: 'flowNode', position: dataPositions.minio, data: { icon: 'drive', label: 'MinIO', sublabel: 'S3 :9000', color: 'pink', size: 'sm' } },
];

const edges: Edge[] = [
  edge('tunnel', 'ui', 'Encrypted tunnel'),
  edge('webhooks', 'dashboard', 'HTTPS'),
  edge('dashboard', 'collector'),
  edge('collector', 'eventstore'),
  edge('eventstore', 'pg'),
  edge('dashboard', 'redis'),
  edge('dashboard', 'minio'),
];

export function DeploymentArchitectureFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={470} />;
}
