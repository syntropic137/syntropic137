'use client';

import type { Node, Edge } from '@xyflow/react';
import { ReactFlowDiagram } from '../ReactFlowDiagram';
import { layoutRow, edge, hedge, NODE_WIDTH } from '../layout';

const CX = 400;

// Layer Y positions
const Y_USER = 0;
const Y_PLATFORM = 120;
const Y_INFRA = 380;
const Y_SECURITY = 500;
const Y_AGENT = 630;
const Y_EXTERNAL = 770;

// User layer
const userPositions = layoutRow(['cli', 'dashboardUi', 'github'], Y_USER + 35, CX, 30);

// Platform — top row (core services)
const corePositions = layoutRow(['fastapi', 'workflowEngine', 'workspaceMgr'], Y_PLATFORM + 40, CX, 30);
// Platform — bottom row (event infrastructure)
const eventPositions = layoutRow(['eventStore', 'projections', 'eventCollector', 'wssse'], Y_PLATFORM + 140, CX, 20, NODE_WIDTH.sm);

// Infrastructure
const infraPositions = layoutRow(['timescaledb', 'redis', 'minio'], Y_INFRA + 35, CX, 30, NODE_WIDTH.sm);

// Security & Proxy
const securityPositions = layoutRow(['envoyProxy', 'tokenInjector', 'dockerSocketProxy'], Y_SECURITY + 35, CX, 30, NODE_WIDTH.sm);

// Agent Execution (agent-net isolated)
const agentPositions = layoutRow(['workspace', 'aiAgent'], Y_AGENT + 35, CX, 40);

// External APIs
const externalPositions = layoutRow(['externalApis'], Y_EXTERNAL + 35, CX, 30);

const nodes: Node[] = [
  // Groups
  {
    id: 'grpUser', type: 'groupNode', position: { x: CX - 300, y: Y_USER },
    data: { title: 'User Layer', color: 'indigo' },
    style: { width: 600, height: 85 },
  },
  {
    id: 'grpPlatform', type: 'groupNode', position: { x: CX - 300, y: Y_PLATFORM },
    data: { title: 'Syn137 Platform', color: 'purple' },
    style: { width: 600, height: 220 },
  },
  {
    id: 'grpInfra', type: 'groupNode', position: { x: CX - 300, y: Y_INFRA },
    data: { title: 'Infrastructure', color: 'slate' },
    style: { width: 600, height: 85 },
  },
  {
    id: 'grpSecurity', type: 'groupNode', position: { x: CX - 300, y: Y_SECURITY },
    data: { title: 'Security & Proxy', color: 'amber' },
    style: { width: 600, height: 85 },
  },
  {
    id: 'grpAgent', type: 'groupNode', position: { x: CX - 230, y: Y_AGENT },
    data: { title: 'Agent Execution (agent-net)', color: 'pink' },
    style: { width: 460, height: 85 },
  },
  {
    id: 'grpExternal', type: 'groupNode', position: { x: CX - 170, y: Y_EXTERNAL },
    data: { title: 'External APIs', color: 'emerald' },
    style: { width: 340, height: 85 },
  },

  // User Layer
  { id: 'cli', type: 'flowNode', position: userPositions.cli, data: { icon: 'terminal', label: 'syn CLI', color: 'indigo' } },
  { id: 'dashboardUi', type: 'flowNode', position: userPositions.dashboardUi, data: { icon: 'monitor', label: 'Dashboard UI', color: 'indigo' } },
  { id: 'github', type: 'flowNode', position: userPositions.github, data: { icon: 'github', label: 'GitHub Events', color: 'indigo' } },

  // Platform — Core
  { id: 'fastapi', type: 'flowNode', position: corePositions.fastapi, data: { icon: 'server', label: 'FastAPI Server', sublabel: ':8000', color: 'purple' } },
  { id: 'workflowEngine', type: 'flowNode', position: corePositions.workflowEngine, data: { icon: 'workflow', label: 'Workflow Engine', color: 'purple' } },
  { id: 'workspaceMgr', type: 'flowNode', position: corePositions.workspaceMgr, data: { icon: 'container', label: 'Workspace Manager', color: 'purple' } },

  // Platform — Event Infrastructure
  { id: 'eventStore', type: 'flowNode', position: eventPositions.eventStore, data: { icon: 'activity', label: 'Event Store', sublabel: 'gRPC', color: 'cyan', size: 'sm' } },
  { id: 'projections', type: 'flowNode', position: eventPositions.projections, data: { icon: 'layers', label: 'Projections', color: 'cyan', size: 'sm' } },
  { id: 'eventCollector', type: 'flowNode', position: eventPositions.eventCollector, data: { icon: 'radio', label: 'Event Collector', sublabel: ':8080', color: 'cyan', size: 'sm' } },
  { id: 'wssse', type: 'flowNode', position: eventPositions.wssse, data: { icon: 'eye', label: 'WebSocket / SSE', color: 'cyan', size: 'sm' } },

  // Infrastructure
  { id: 'timescaledb', type: 'flowNode', position: infraPositions.timescaledb, data: { icon: 'database', label: 'TimescaleDB', sublabel: 'Events + Metrics', color: 'emerald', size: 'sm' } },
  { id: 'redis', type: 'flowNode', position: infraPositions.redis, data: { icon: 'zap', label: 'Redis', sublabel: 'Cache + Pub/Sub', color: 'amber', size: 'sm' } },
  { id: 'minio', type: 'flowNode', position: infraPositions.minio, data: { icon: 'drive', label: 'MinIO', sublabel: 'S3 Artifacts', color: 'pink', size: 'sm' } },

  // Security & Proxy
  { id: 'envoyProxy', type: 'flowNode', position: securityPositions.envoyProxy, data: { icon: 'shield', label: 'envoy-proxy', sublabel: ':8081', color: 'amber', size: 'sm' } },
  { id: 'tokenInjector', type: 'flowNode', position: securityPositions.tokenInjector, data: { icon: 'lock', label: 'token-injector', sublabel: 'ext_authz :9002', color: 'amber', size: 'sm' } },
  { id: 'dockerSocketProxy', type: 'flowNode', position: securityPositions.dockerSocketProxy, data: { icon: 'container', label: 'docker-socket-proxy', sublabel: ':2375', color: 'amber', size: 'sm' } },

  // Agent Execution (agent-net network isolation)
  { id: 'workspace', type: 'flowNode', position: agentPositions.workspace, data: { icon: 'container', label: 'Isolated Workspace', sublabel: 'Docker / agent-net', color: 'pink' } },
  { id: 'aiAgent', type: 'flowNode', position: agentPositions.aiAgent, data: { icon: 'zap', label: 'Claude / AI Agent', sublabel: 'no real API keys', color: 'pink' } },

  // External APIs
  { id: 'externalApis', type: 'flowNode', position: externalPositions.externalApis, data: { icon: 'globe', label: 'External APIs', sublabel: 'Anthropic, GitHub, PyPI, npm', color: 'emerald' } },
];

const edges: Edge[] = [
  // User → Platform
  edge('cli', 'fastapi', 'REST / WebSocket'),
  edge('dashboardUi', 'fastapi'),
  edge('github', 'fastapi', 'Webhooks'),
  // Platform internal — horizontal within rows
  hedge('fastapi', 'workflowEngine'),
  hedge('workflowEngine', 'workspaceMgr'),
  edge('fastapi', 'eventStore'),
  hedge('eventStore', 'projections'),
  hedge('eventCollector', 'wssse'),
  // Platform → Infrastructure
  edge('eventStore', 'timescaledb', 'Events'),
  edge('projections', 'redis', 'Cache'),
  edge('workspaceMgr', 'minio', 'Artifacts', 'slow'),
  // Platform → Security
  edge('fastapi', 'dockerSocketProxy', 'Docker API'),
  // Platform → Agent
  edge('workspaceMgr', 'workspace', 'Isolated Execution'),
  hedge('workspace', 'aiAgent'),
  // Agent → Security (egress path — the key security story)
  edge('aiAgent', 'envoyProxy', 'Egress via proxy URL'),
  // Security internal
  hedge('envoyProxy', 'tokenInjector', 'ext_authz'),
  // Security → External APIs (credentials injected at egress)
  edge('envoyProxy', 'externalApis', 'Real API keys injected'),
];

export function SystemArchitectureFlow() {
  return <ReactFlowDiagram nodes={nodes} edges={edges} minHeight={900} />;
}
