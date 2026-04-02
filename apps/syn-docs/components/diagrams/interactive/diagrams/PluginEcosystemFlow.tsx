'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { edge, hedge } from '../layout';

// Syntropic137 Plugin Ecosystem (left group)
const SX = 90;
// Claude Code Plugin (right group)
const CX = 440;

const nodes: Node[] = [
  // ── Groups ──
  {
    id: 'grpSyn', type: 'groupNode', position: { x: 20, y: 0 },
    data: { title: 'Syntropic137 Plugin Ecosystem', color: 'purple' },
    style: { width: 290, height: 350 },
  },
  {
    id: 'grpCC', type: 'groupNode', position: { x: 370, y: 0 },
    data: { title: 'Claude Code Plugin', color: 'cyan' },
    style: { width: 260, height: 350 },
  },

  // ── Syntropic137 side ──
  {
    id: 'marketplace', type: 'flowNode', position: { x: SX, y: 40 },
    data: { icon: 'globe', label: 'Marketplace', sublabel: 'GitHub registries', color: 'purple', size: 'sm' },
  },
  {
    id: 'plugin', type: 'flowNode', position: { x: SX, y: 110 },
    data: { icon: 'plug', label: 'Plugin Package', sublabel: 'syntropic137-plugin.json', color: 'indigo', size: 'sm' },
  },
  {
    id: 'workflows', type: 'flowNode', position: { x: 40, y: 185 },
    data: { icon: 'workflow', label: 'Workflows', sublabel: 'workflow.yaml + phases/', color: 'emerald', size: 'sm' },
  },
  {
    id: 'triggers', type: 'flowNode', position: { x: 195, y: 185 },
    data: { icon: 'zap', label: 'Triggers', sublabel: 'Planned', color: 'amber', size: 'sm' },
  },
  {
    id: 'platform', type: 'flowNode', position: { x: SX, y: 270 },
    data: { icon: 'server', label: 'Syntropic137', sublabel: 'Orchestration + Observability', color: 'pink', size: 'sm' },
  },

  // ── Claude Code side ──
  {
    id: 'ccAgent', type: 'flowNode', position: { x: CX, y: 40 },
    data: { icon: 'terminal', label: 'Claude Code', sublabel: 'Agent / IDE', color: 'cyan', size: 'sm' },
  },
  {
    id: 'commands', type: 'flowNode', position: { x: CX, y: 120 },
    data: { icon: 'send', label: '/syn-* Commands', sublabel: '7 slash commands', color: 'indigo', size: 'sm' },
  },
  {
    id: 'skills', type: 'flowNode', position: { x: CX, y: 200 },
    data: { icon: 'layers', label: 'Domain Skills', sublabel: '7 contextual skills', color: 'emerald', size: 'sm' },
  },
  {
    id: 'api', type: 'flowNode', position: { x: CX, y: 280 },
    data: { icon: 'radio', label: 'syn-api', sublabel: 'REST + SSE', color: 'cyan', size: 'sm' },
  },
];

const edges: Edge[] = [
  // Syntropic137 plugin flow
  edge('marketplace', 'plugin', 'discover + install'),
  edge('plugin', 'workflows'),
  edge('plugin', 'triggers'),
  edge('workflows', 'platform', 'ingested'),
  edge('triggers', 'platform', 'configured'),

  // Claude Code plugin flow
  edge('ccAgent', 'commands'),
  edge('commands', 'skills'),
  edge('skills', 'api', 'operates'),

  // Cross-boundary: CC plugin talks to the platform
  hedge('api', 'platform'),
];

export function PluginEcosystemFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={410} />;
}
