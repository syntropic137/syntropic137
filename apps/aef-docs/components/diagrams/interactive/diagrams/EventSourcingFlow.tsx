'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, hedge, NODE_WIDTH } from '../layout';

const CX = 300;

// Row 1: Command → Aggregate → Domain Event
const row1 = layoutRow(['command', 'aggregate', 'event'], 40, CX, 30);
// Row 2: Event Store → Projections → Read Models
const row2 = layoutRow(['store', 'projections', 'readModels'], 140, CX, 30);

const nodes: Node[] = [
  { id: 'command', type: 'flowNode', position: row1.command, data: { icon: 'send', label: 'Command', color: 'indigo' } },
  { id: 'aggregate', type: 'flowNode', position: row1.aggregate, data: { icon: 'shield', label: 'Aggregate', sublabel: 'Validate', color: 'purple' } },
  { id: 'event', type: 'flowNode', position: row1.event, data: { icon: 'zap', label: 'Domain Event', color: 'pink' } },
  { id: 'store', type: 'flowNode', position: row2.store, data: { icon: 'database', label: 'Event Store', color: 'cyan' } },
  { id: 'projections', type: 'flowNode', position: row2.projections, data: { icon: 'layers', label: 'Projections', color: 'emerald' } },
  { id: 'readModels', type: 'flowNode', position: row2.readModels, data: { icon: 'eye', label: 'Read Models', color: 'amber' } },
];

const edges: Edge[] = [
  hedge('command', 'aggregate'),
  hedge('aggregate', 'event'),
  edge('event', 'store'),
  hedge('store', 'projections'),
  hedge('projections', 'readModels'),
];

export function EventSourcingFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={260} />;
}
