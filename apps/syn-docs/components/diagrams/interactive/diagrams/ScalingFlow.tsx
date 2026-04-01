'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, NODE_WIDTH } from '../layout';

const CX = 400;

const row1 = layoutRow(['lb'], 35, CX, 0);
const row2 = layoutRow(['s1', 's2', 's3'], 145, CX, 30, NODE_WIDTH.sm);
const row3 = layoutRow(['pg', 'redis', 'minio'], 255, CX, 30, NODE_WIDTH.sm);

// Group nodes
const groupNodes: Node[] = [
  {
    id: 'grpLb', type: 'groupNode', position: { x: CX - 130, y: 0 },
    data: { title: 'Load Balancer', color: 'indigo' },
    style: { width: 260, height: 95 },
  },
  {
    id: 'grpServers', type: 'groupNode', position: { x: CX - 280, y: 110 },
    data: { title: 'Servers', color: 'purple' },
    style: { width: 560, height: 95 },
  },
  {
    id: 'grpData', type: 'groupNode', position: { x: CX - 280, y: 220 },
    data: { title: 'Data Stores', color: 'emerald' },
    style: { width: 560, height: 95 },
  },
];

const flowNodes: Node[] = [
  { id: 'lb', type: 'flowNode', position: row1.lb, data: { icon: 'globe', label: 'least_conn', color: 'indigo' } },
  { id: 's1', type: 'flowNode', position: row2.s1, data: { icon: 'server', label: 'Syn137 Server 1', color: 'purple', size: 'sm' } },
  { id: 's2', type: 'flowNode', position: row2.s2, data: { icon: 'server', label: 'Syn137 Server 2', color: 'purple', size: 'sm' } },
  { id: 's3', type: 'flowNode', position: row2.s3, data: { icon: 'server', label: 'Syn137 Server 3', color: 'purple', size: 'sm' } },
  { id: 'pg', type: 'flowNode', position: row3.pg, data: { icon: 'database', label: 'TimescaleDB', color: 'emerald', size: 'sm' } },
  { id: 'redis', type: 'flowNode', position: row3.redis, data: { icon: 'zap', label: 'Redis', color: 'amber', size: 'sm' } },
  { id: 'minio', type: 'flowNode', position: row3.minio, data: { icon: 'drive', label: 'MinIO (S3)', color: 'pink', size: 'sm' } },
];

const nodes: Node[] = [...groupNodes, ...flowNodes];

const edges: Edge[] = [
  edge('lb', 's1'),
  edge('lb', 's2'),
  edge('lb', 's3'),
  edge('s1', 'pg', undefined, 'slow'),
  edge('s2', 'redis', 'Shared state', 'slow'),
  edge('s3', 'minio', undefined, 'slow'),
];

export function ScalingFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={360} />;
}
