'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { edge } from '../layout';

// Domain side (left) — centered in group
const DX = 90;
// Observability side (right) — centered in group
const OX = 410;

const GRP_H = 290;

const nodes: Node[] = [
  // Groups — equal height
  {
    id: 'grpDomain', type: 'groupNode', position: { x: 20, y: 0 },
    data: { title: 'Domain Events', color: 'purple' },
    style: { width: 260, height: GRP_H },
  },
  {
    id: 'grpObs', type: 'groupNode', position: { x: 340, y: 0 },
    data: { title: 'Observability Events', color: 'cyan' },
    style: { width: 260, height: GRP_H },
  },
  // Domain Events — 4 vertical
  { id: 'command', type: 'flowNode', position: { x: DX, y: 40 }, data: { icon: 'send', label: 'Command', color: 'indigo', size: 'sm' } },
  { id: 'aggregate', type: 'flowNode', position: { x: DX, y: 105 }, data: { icon: 'shield', label: 'Aggregate', color: 'purple', size: 'sm' } },
  { id: 'domainEvent', type: 'flowNode', position: { x: DX, y: 170 }, data: { icon: 'zap', label: 'Event', color: 'pink', size: 'sm' } },
  { id: 'eventStore', type: 'flowNode', position: { x: DX, y: 240 }, data: { icon: 'database', label: 'Event Store', color: 'purple', size: 'sm' } },
  // Observability Events — 4 vertical
  { id: 'agentOutput', type: 'flowNode', position: { x: OX, y: 40 }, data: { icon: 'zap', label: 'Agent JSONL', color: 'cyan', size: 'sm' } },
  { id: 'collector', type: 'flowNode', position: { x: OX, y: 105 }, data: { icon: 'radio', label: 'Collector', sublabel: 'HTTP ingest', color: 'cyan', size: 'sm' } },
  { id: 'eventBuffer', type: 'flowNode', position: { x: OX, y: 170 }, data: { icon: 'layers', label: 'Event Buffer', color: 'emerald', size: 'sm' } },
  { id: 'timescale', type: 'flowNode', position: { x: OX, y: 240 }, data: { icon: 'database', label: 'TimescaleDB', sublabel: 'Hypertable', color: 'cyan', size: 'sm' } },
];

const edges: Edge[] = [
  edge('command', 'aggregate'),
  edge('aggregate', 'domainEvent'),
  edge('domainEvent', 'eventStore', 'gRPC'),
  edge('agentOutput', 'collector'),
  edge('collector', 'eventBuffer'),
  edge('eventBuffer', 'timescale', 'Batched write'),
];

export function TwoEventTypesFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={340} />;
}
