'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, hedge, NODE_WIDTH } from '../layout';

const CX = 400;

const setupPositions = layoutRow(
  ['inject', 'configGit', 'setupGh', 'clearTokens'],
  140, CX, 15, NODE_WIDTH.sm,
);

const agentPositions = layoutRow(
  ['agent', 'cachedCreds', 'streamEvents', 'artifacts'],
  260, CX, 15, NODE_WIDTH.sm,
);

const nodes: Node[] = [
  // Outer group
  {
    id: 'grpLifecycle', type: 'groupNode', position: { x: CX - 320, y: 0 },
    data: { title: 'Workspace Lifecycle', color: 'purple' },
    style: { width: 640, height: 380 },
  },
  // Step 1: Create
  { id: 'create', type: 'flowNode', position: { x: CX - 85, y: 40 }, data: { icon: 'play', label: '1. Create Container', color: 'indigo' } },
  // Setup Phase
  {
    id: 'grpSetup', type: 'groupNode', position: { x: CX - 305, y: 100 },
    data: { title: 'Setup Phase — Secrets available', color: 'amber' },
    style: { width: 610, height: 85 },
  },
  { id: 'inject', type: 'flowNode', position: setupPositions.inject, data: { icon: 'lock', label: 'Inject Token', color: 'amber', size: 'sm' } },
  { id: 'configGit', type: 'flowNode', position: setupPositions.configGit, data: { icon: 'git', label: 'Configure git', color: 'amber', size: 'sm' } },
  { id: 'setupGh', type: 'flowNode', position: setupPositions.setupGh, data: { icon: 'terminal', label: 'Setup gh CLI', color: 'amber', size: 'sm' } },
  { id: 'clearTokens', type: 'flowNode', position: setupPositions.clearTokens, data: { icon: 'unlock', label: 'Clear tokens', color: 'pink', size: 'sm' } },
  // Agent Phase
  {
    id: 'grpAgent', type: 'groupNode', position: { x: CX - 305, y: 220 },
    data: { title: 'Agent Phase — Only ANTHROPIC_API_KEY', color: 'purple' },
    style: { width: 610, height: 85 },
  },
  { id: 'agent', type: 'flowNode', position: agentPositions.agent, data: { icon: 'zap', label: 'AI Agent', color: 'purple', size: 'sm' } },
  { id: 'cachedCreds', type: 'flowNode', position: agentPositions.cachedCreds, data: { icon: 'git', label: 'Cached creds', color: 'emerald', size: 'sm' } },
  { id: 'streamEvents', type: 'flowNode', position: agentPositions.streamEvents, data: { icon: 'radio', label: 'Stream events', color: 'cyan', size: 'sm' } },
  { id: 'artifacts', type: 'flowNode', position: agentPositions.artifacts, data: { icon: 'drive', label: 'Artifacts', color: 'pink', size: 'sm' } },
  // Step 2: Destroy
  { id: 'destroy', type: 'flowNode', position: { x: CX - 85, y: 340 }, data: { icon: 'stop', label: '2. Destroy Container', color: 'slate' } },
];

const edges: Edge[] = [
  // Vertical: create → first setup node
  edge('create', 'inject'),
  // Horizontal: setup phase pipeline (left → right)
  hedge('inject', 'configGit'),
  hedge('configGit', 'setupGh'),
  hedge('setupGh', 'clearTokens'),
  // Vertical: last setup → first agent
  edge('clearTokens', 'agent'),
  // Horizontal: agent phase (left → right)
  hedge('agent', 'cachedCreds'),
  hedge('agent', 'streamEvents'),
  hedge('agent', 'artifacts'),
  // Vertical: agent → destroy
  edge('agent', 'destroy', 'Cleanup', 'slow'),
];

export function WorkspaceIsolationFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={430} />;
}
