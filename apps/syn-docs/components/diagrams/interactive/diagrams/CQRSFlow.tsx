'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { edge, hedge } from '../layout';

// Write side (left column) — centered in group
const WX = 100;
// Read side (right column) — centered in group
const RX = 420;

const GRP_H = 280;

const nodes: Node[] = [
  // Groups — equal height
  {
    id: 'grpWrite', type: 'groupNode', position: { x: 20, y: 0 },
    data: { title: 'Write Side', color: 'purple' },
    style: { width: 260, height: GRP_H },
  },
  {
    id: 'grpRead', type: 'groupNode', position: { x: 340, y: 0 },
    data: { title: 'Read Side', color: 'cyan' },
    style: { width: 260, height: GRP_H },
  },
  // Write Side nodes — 4 vertically stacked
  { id: 'commands', type: 'flowNode', position: { x: WX, y: 40 }, data: { icon: 'send', label: 'Commands', color: 'indigo', size: 'sm' } },
  { id: 'aggregates', type: 'flowNode', position: { x: WX, y: 105 }, data: { icon: 'shield', label: 'Aggregates', color: 'purple', size: 'sm' } },
  { id: 'events', type: 'flowNode', position: { x: WX, y: 170 }, data: { icon: 'zap', label: 'Events', color: 'pink', size: 'sm' } },
  { id: 'eventStore', type: 'flowNode', position: { x: WX, y: 230 }, data: { icon: 'database', label: 'Event Store', color: 'purple', size: 'sm' } },
  // Read Side nodes — 3 vertically stacked, centered
  { id: 'projections', type: 'flowNode', position: { x: RX, y: 50 }, data: { icon: 'layers', label: 'Projections', color: 'cyan', size: 'sm' } },
  { id: 'cache', type: 'flowNode', position: { x: RX, y: 130 }, data: { icon: 'zap', label: 'Redis Cache', color: 'amber', size: 'sm' } },
  { id: 'queryApi', type: 'flowNode', position: { x: RX, y: 210 }, data: { icon: 'server', label: 'Query API', sublabel: 'sub-ms cached', color: 'emerald', size: 'sm' } },
];

const edges: Edge[] = [
  edge('commands', 'aggregates'),
  edge('aggregates', 'events'),
  edge('events', 'eventStore'),
  // Cross-side: events feed projections
  hedge('eventStore', 'projections', 'Subscribe'),
  edge('projections', 'cache'),
  edge('cache', 'queryApi'),
];

export function CQRSFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={320} />;
}
