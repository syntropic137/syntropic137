'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, hedge, NODE_WIDTH } from '../layout';

// 4 bounded context columns — wider spacing, uniform groups
const COL_GAP = 190;
const COL1 = 0;
const COL2 = COL1 + COL_GAP;
const COL3 = COL2 + COL_GAP;
const COL4 = COL3 + COL_GAP;
const GRP_W = 170;
const GRP_H = 230; // uniform height for all groups
const GRP_TOP = 0;
const NODE_X_OFFSET = 15; // center sm nodes (140px) in 170px group

// Bottom pipeline — use layoutRow for even spacing
const PIPELINE_Y = 270;
const PIPELINE_CX = (COL4 + GRP_W) / 2; // center under the groups

const pipelinePositions = layoutRow(
  ['pTrigger', 'pWorkflow', 'pExecution', 'pWorkspace', 'pSession', 'pArtifact'],
  PIPELINE_Y,
  PIPELINE_CX,
  10,
  NODE_WIDTH.sm,
);

const nodes: Node[] = [
  // Context Groups — all same height for visual balance
  {
    id: 'grpOrch', type: 'groupNode', position: { x: COL1, y: GRP_TOP },
    data: { title: 'Orchestration', color: 'indigo' },
    style: { width: GRP_W, height: GRP_H },
  },
  {
    id: 'grpSessions', type: 'groupNode', position: { x: COL2, y: GRP_TOP },
    data: { title: 'Sessions', color: 'purple' },
    style: { width: GRP_W, height: GRP_H },
  },
  {
    id: 'grpGithub', type: 'groupNode', position: { x: COL3, y: GRP_TOP },
    data: { title: 'GitHub', color: 'pink' },
    style: { width: GRP_W, height: GRP_H },
  },
  {
    id: 'grpArtifacts', type: 'groupNode', position: { x: COL4, y: GRP_TOP },
    data: { title: 'Artifacts', color: 'cyan' },
    style: { width: GRP_W, height: GRP_H },
  },

  // Orchestration nodes — 3 vertically stacked
  { id: 'workflow', type: 'flowNode', position: { x: COL1 + NODE_X_OFFSET, y: 40 }, data: { icon: 'workflow', label: 'Workflow', color: 'indigo', size: 'sm' } },
  { id: 'execution', type: 'flowNode', position: { x: COL1 + NODE_X_OFFSET, y: 110 }, data: { icon: 'play', label: 'Execution', color: 'indigo', size: 'sm' } },
  { id: 'workspace', type: 'flowNode', position: { x: COL1 + NODE_X_OFFSET, y: 180 }, data: { icon: 'container', label: 'Workspace', color: 'indigo', size: 'sm' } },

  // Sessions — 1 node, vertically centered in group
  { id: 'session', type: 'flowNode', position: { x: COL2 + NODE_X_OFFSET, y: 100 }, data: { icon: 'activity', label: 'Session', color: 'purple', size: 'sm' } },

  // GitHub — 2 nodes
  { id: 'installation', type: 'flowNode', position: { x: COL3 + NODE_X_OFFSET, y: 70 }, data: { icon: 'github', label: 'Installation', color: 'pink', size: 'sm' } },
  { id: 'triggers', type: 'flowNode', position: { x: COL3 + NODE_X_OFFSET, y: 140 }, data: { icon: 'zap', label: 'Triggers', color: 'pink', size: 'sm' } },

  // Artifacts — 1 node, vertically centered
  { id: 'artifactStore', type: 'flowNode', position: { x: COL4 + NODE_X_OFFSET, y: 100 }, data: { icon: 'drive', label: 'Artifact Store', color: 'cyan', size: 'sm' } },

  // Bottom pipeline — evenly spaced
  { id: 'pTrigger', type: 'flowNode', position: pipelinePositions.pTrigger, data: { icon: 'git', label: 'Trigger', color: 'pink', size: 'sm' } },
  { id: 'pWorkflow', type: 'flowNode', position: pipelinePositions.pWorkflow, data: { icon: 'workflow', label: 'Workflow', color: 'indigo', size: 'sm' } },
  { id: 'pExecution', type: 'flowNode', position: pipelinePositions.pExecution, data: { icon: 'play', label: 'Execution', color: 'indigo', size: 'sm' } },
  { id: 'pWorkspace', type: 'flowNode', position: pipelinePositions.pWorkspace, data: { icon: 'container', label: 'Workspace', color: 'indigo', size: 'sm' } },
  { id: 'pSession', type: 'flowNode', position: pipelinePositions.pSession, data: { icon: 'activity', label: 'Session', color: 'purple', size: 'sm' } },
  { id: 'pArtifact', type: 'flowNode', position: pipelinePositions.pArtifact, data: { icon: 'drive', label: 'Artifact', color: 'cyan', size: 'sm' } },
];

const edges: Edge[] = [
  // Orchestration vertical
  edge('workflow', 'execution'),
  edge('execution', 'workspace'),
  // GitHub vertical
  edge('installation', 'triggers'),
  // Pipeline (horizontal)
  hedge('pTrigger', 'pWorkflow'),
  hedge('pWorkflow', 'pExecution'),
  hedge('pExecution', 'pWorkspace'),
  hedge('pWorkspace', 'pSession'),
  hedge('pSession', 'pArtifact'),
];

export function DomainModelFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={360} />;
}
