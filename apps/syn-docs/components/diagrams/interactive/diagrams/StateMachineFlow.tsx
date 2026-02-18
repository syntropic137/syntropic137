'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, hedge } from '../layout';

const CX = 350;

const terminalPositions = layoutRow(
  ['paused', 'completed', 'failed', 'cancelled'],
  160, CX, 20, 140,
);

const nodes: Node[] = [
  { id: 'pending', type: 'flowNode', position: { x: CX - 190, y: 20 }, data: { icon: 'pause', label: 'PENDING', color: 'slate' } },
  { id: 'running', type: 'flowNode', position: { x: CX + 20, y: 20 }, data: { icon: 'play', label: 'RUNNING', color: 'indigo' } },
  { id: 'paused', type: 'flowNode', position: terminalPositions.paused, data: { icon: 'pause', label: 'PAUSED', sublabel: 'pause / resume', color: 'amber', size: 'sm' } },
  { id: 'completed', type: 'flowNode', position: terminalPositions.completed, data: { icon: 'check', label: 'COMPLETED', sublabel: 'success', color: 'emerald', size: 'sm' } },
  { id: 'failed', type: 'flowNode', position: terminalPositions.failed, data: { icon: 'x', label: 'FAILED', sublabel: 'error', color: 'pink', size: 'sm' } },
  { id: 'cancelled', type: 'flowNode', position: terminalPositions.cancelled, data: { icon: 'stop', label: 'CANCELLED', sublabel: 'cancel', color: 'slate', size: 'sm' } },
];

const edges: Edge[] = [
  hedge('pending', 'running'),
  edge('running', 'paused', 'transitions'),
  edge('running', 'completed'),
  edge('running', 'failed'),
  edge('running', 'cancelled'),
];

export function StateMachineFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={260} />;
}
