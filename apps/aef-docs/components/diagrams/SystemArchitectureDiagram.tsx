'use client';

import {
  Diagram, DiagramGroup, DiagramNode, DiagramArrow,
  DiagramGrid, DiagramSeparator,
} from './DiagramPrimitives';

export function SystemArchitectureDiagram() {
  return (
    <Diagram>
      {/* User Layer — 3 equal-width entry points */}
      <DiagramGroup title="User Layer" color="indigo" columns={3} className="w-full">
        <DiagramNode icon="terminal" label="aef CLI" color="indigo" />
        <DiagramNode icon="monitor" label="Dashboard UI" color="indigo" />
        <DiagramNode icon="github" label="GitHub Events" color="indigo" />
      </DiagramGroup>

      <DiagramArrow label="REST / WebSocket / Webhooks" />

      {/* Platform — structured into service tiers */}
      <DiagramGroup title="AEF Platform" color="purple" className="w-full">
        <DiagramGrid columns={3}>
          <DiagramNode icon="server" label="FastAPI Server" sublabel=":8000" color="purple" />
          <DiagramNode icon="workflow" label="Workflow Engine" color="purple" />
          <DiagramNode icon="container" label="Workspace Manager" color="purple" />
        </DiagramGrid>
        <DiagramSeparator />
        <DiagramGrid columns={4}>
          <DiagramNode icon="activity" label="Event Store" sublabel="gRPC" color="cyan" />
          <DiagramNode icon="layers" label="Projections" color="cyan" />
          <DiagramNode icon="radio" label="Event Collector" sublabel=":8080" color="cyan" />
          <DiagramNode icon="eye" label="WebSocket / SSE" color="cyan" />
        </DiagramGrid>
      </DiagramGroup>

      <DiagramArrow label="Events / Queries / Artifacts" />

      {/* Infrastructure — 3 data stores */}
      <DiagramGroup title="Infrastructure" color="slate" columns={3} className="w-full">
        <DiagramNode icon="database" label="TimescaleDB" sublabel="Events + Metrics" color="emerald" />
        <DiagramNode icon="zap" label="Redis" sublabel="Cache + Pub/Sub" color="amber" />
        <DiagramNode icon="drive" label="MinIO" sublabel="S3 Artifacts" color="pink" />
      </DiagramGroup>

      <DiagramArrow label="Isolated Execution" />

      {/* Agent Execution */}
      <DiagramGroup title="Agent Execution" color="pink" columns={2} className="w-full">
        <DiagramNode icon="container" label="Isolated Workspace" sublabel="Docker" color="pink" />
        <DiagramNode icon="zap" label="Claude / AI Agent" color="pink" />
      </DiagramGroup>
    </Diagram>
  );
}
