'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, hedge, NODE_WIDTH } from '../layout';

const CX = 380;

// Layer Y positions
const Y_EXT = 0;
const Y_APP = 120;
const Y_DATA = 390;
const Y_AGENT = 490;
const Y_EXTERNAL = 590;

// External Access — 2 nodes centered
const extPositions = layoutRow(['tunnel', 'webhooks'], Y_EXT + 35, CX, 40);

// Frontend — single node
const frontPos = { x: CX - 290, y: Y_APP + 50 };

// Backend — stacked nodes with envoy, token-injector, docker-socket-proxy added
const backPositions = {
  gateway: { x: CX + 20, y: Y_APP + 35 },
  dashboard: { x: CX + 20, y: Y_APP + 95 },
  collector: { x: CX + 20, y: Y_APP + 155 },
  eventstore: { x: CX + 20, y: Y_APP + 215 },
};

// Security sidecar — stacked in its own group
const securityPositions = {
  envoyProxy: { x: CX + 290, y: Y_APP + 35 },
  tokenInjector: { x: CX + 290, y: Y_APP + 95 },
  dockerSocketProxy: { x: CX + 290, y: Y_APP + 155 },
};

// Data layer — 3 nodes centered
const dataPositions = layoutRow(['pg', 'redis', 'minio'], Y_DATA + 35, CX, 30, NODE_WIDTH.sm);

// Agent execution — agent-net isolated
const agentPositions = layoutRow(['workspace', 'agent'], Y_AGENT + 35, CX, 40, NODE_WIDTH.sm);

// External APIs
const externalPositions = layoutRow(['externalApis'], Y_EXTERNAL + 35, CX, 30, NODE_WIDTH.sm);

const nodes: Node[] = [
  // Groups
  {
    id: 'grpExt', type: 'groupNode', position: { x: CX - 290, y: Y_EXT },
    data: { title: 'External Access', color: 'indigo' },
    style: { width: 700, height: 90 },
  },
  {
    id: 'grpFront', type: 'groupNode', position: { x: CX - 310, y: Y_APP },
    data: { title: 'Frontend', color: 'purple' },
    style: { width: 200, height: 120 },
  },
  {
    id: 'grpBack', type: 'groupNode', position: { x: CX - 10, y: Y_APP },
    data: { title: 'Backend', color: 'cyan' },
    style: { width: 230, height: 260 },
  },
  {
    id: 'grpSecurity', type: 'groupNode', position: { x: CX + 260, y: Y_APP },
    data: { title: 'Security & Proxy', color: 'amber' },
    style: { width: 180, height: 210 },
  },
  {
    id: 'grpData', type: 'groupNode', position: { x: CX - 310, y: Y_DATA },
    data: { title: 'Data Layer', color: 'emerald' },
    style: { width: 700, height: 90 },
  },
  {
    id: 'grpAgent', type: 'groupNode', position: { x: CX - 180, y: Y_AGENT },
    data: { title: 'Agent Execution (agent-net)', color: 'pink' },
    style: { width: 400, height: 80 },
  },
  {
    id: 'grpExternal', type: 'groupNode', position: { x: CX - 130, y: Y_EXTERNAL },
    data: { title: 'External APIs', color: 'emerald' },
    style: { width: 300, height: 80 },
  },

  // External
  { id: 'tunnel', type: 'flowNode', position: extPositions.tunnel, data: { icon: 'globe', label: 'Cloudflare Tunnel', color: 'indigo' } },
  { id: 'webhooks', type: 'flowNode', position: extPositions.webhooks, data: { icon: 'github', label: 'GitHub Webhooks', color: 'indigo' } },

  // Frontend
  { id: 'ui', type: 'flowNode', position: frontPos, data: { icon: 'monitor', label: 'Dashboard UI', sublabel: 'React', color: 'purple', size: 'sm' } },

  // Backend
  { id: 'gateway', type: 'flowNode', position: backPositions.gateway, data: { icon: 'shield', label: 'gateway', sublabel: 'nginx :80', color: 'cyan', size: 'sm' } },
  { id: 'dashboard', type: 'flowNode', position: backPositions.dashboard, data: { icon: 'server', label: 'syn-api', sublabel: 'FastAPI :8000', color: 'cyan', size: 'sm' } },
  { id: 'collector', type: 'flowNode', position: backPositions.collector, data: { icon: 'radio', label: 'event-collector', sublabel: ':8080', color: 'cyan', size: 'sm' } },
  { id: 'eventstore', type: 'flowNode', position: backPositions.eventstore, data: { icon: 'activity', label: 'event-store', sublabel: 'gRPC :50051', color: 'cyan', size: 'sm' } },

  // Security & Proxy
  { id: 'envoyProxy', type: 'flowNode', position: securityPositions.envoyProxy, data: { icon: 'shield', label: 'envoy-proxy', sublabel: ':8081', color: 'amber', size: 'sm' } },
  { id: 'tokenInjector', type: 'flowNode', position: securityPositions.tokenInjector, data: { icon: 'lock', label: 'token-injector', sublabel: 'ext_authz :9002', color: 'amber', size: 'sm' } },
  { id: 'dockerSocketProxy', type: 'flowNode', position: securityPositions.dockerSocketProxy, data: { icon: 'container', label: 'docker-socket-proxy', sublabel: ':2375', color: 'amber', size: 'sm' } },

  // Data
  { id: 'pg', type: 'flowNode', position: dataPositions.pg, data: { icon: 'database', label: 'TimescaleDB', sublabel: 'PostgreSQL :5432', color: 'emerald', size: 'sm' } },
  { id: 'redis', type: 'flowNode', position: dataPositions.redis, data: { icon: 'zap', label: 'Redis', sublabel: ':6379', color: 'amber', size: 'sm' } },
  { id: 'minio', type: 'flowNode', position: dataPositions.minio, data: { icon: 'drive', label: 'MinIO', sublabel: 'S3 :9000', color: 'pink', size: 'sm' } },

  // Agent Execution (agent-net)
  { id: 'workspace', type: 'flowNode', position: agentPositions.workspace, data: { icon: 'container', label: 'Workspace', sublabel: 'Docker', color: 'pink', size: 'sm' } },
  { id: 'agent', type: 'flowNode', position: agentPositions.agent, data: { icon: 'zap', label: 'AI Agent', sublabel: 'no real keys', color: 'pink', size: 'sm' } },

  // External APIs
  { id: 'externalApis', type: 'flowNode', position: externalPositions.externalApis, data: { icon: 'globe', label: 'External APIs', sublabel: 'Anthropic, GitHub, PyPI, npm', color: 'emerald', size: 'sm' } },
];

const edges: Edge[] = [
  // External → Frontend/Backend
  edge('tunnel', 'gateway', 'Encrypted tunnel'),
  edge('webhooks', 'dashboard', 'HTTPS'),
  // Frontend → Backend
  edge('ui', 'gateway', 'HTTP'),
  // Backend internal
  edge('gateway', 'dashboard', 'Reverse proxy'),
  edge('dashboard', 'collector'),
  edge('collector', 'eventstore'),
  // Backend → Data
  edge('eventstore', 'pg'),
  edge('dashboard', 'redis'),
  edge('dashboard', 'minio'),
  // Backend → Security
  edge('dashboard', 'dockerSocketProxy', 'Docker API'),
  // Security internal
  hedge('envoyProxy', 'tokenInjector', 'ext_authz'),
  // Agent execution
  edge('dashboard', 'workspace', 'Provision'),
  hedge('workspace', 'agent'),
  // Agent → Proxy (egress)
  edge('agent', 'envoyProxy', 'Egress'),
  // Proxy → External APIs
  edge('envoyProxy', 'externalApis', 'Keys injected'),
];

export function DeploymentArchitectureFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={720} />;
}
