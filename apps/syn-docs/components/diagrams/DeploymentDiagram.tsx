'use client';

import {
  Diagram, DiagramGroup, DiagramNode, DiagramArrow,
  DiagramGrid, DiagramSeparator,
} from './DiagramPrimitives';

export function DeploymentArchitectureDiagram() {
  return (
    <Diagram>
      {/* External Access */}
      <DiagramGroup title="External Access" color="indigo" columns={2} className="w-full">
        <DiagramNode icon="globe" label="Cloudflare Tunnel" color="indigo" />
        <DiagramNode icon="github" label="GitHub Webhooks" color="indigo" />
      </DiagramGroup>

      <DiagramArrow label="Encrypted tunnel / HTTPS" />

      {/* Application Layer */}
      <DiagramGrid columns={2} className="items-start">
        <DiagramGroup title="Frontend" color="purple" className="h-full">
          <DiagramNode icon="monitor" label="gateway" sublabel="nginx :80" color="purple" />
        </DiagramGroup>

        <DiagramGroup title="Backend" color="cyan" columns={1} className="h-full">
          <DiagramNode icon="server" label="syn-api" sublabel="FastAPI :8000" color="cyan" />
          <DiagramNode icon="radio" label="event-collector" sublabel=":8080" color="cyan" />
          <DiagramNode icon="activity" label="event-store" sublabel="gRPC :50051" color="cyan" />
        </DiagramGroup>
      </DiagramGrid>

      <DiagramArrow label="Connections" />

      {/* Data Layer */}
      <DiagramGroup title="Data Layer" color="emerald" columns={3} className="w-full">
        <DiagramNode icon="database" label="TimescaleDB" sublabel="PostgreSQL :5432" color="emerald" />
        <DiagramNode icon="zap" label="Redis" sublabel=":6379" color="amber" />
        <DiagramNode icon="drive" label="MinIO" sublabel="S3 :9000" color="pink" />
      </DiagramGroup>
    </Diagram>
  );
}

export function WorkspaceIsolationDiagram() {
  return (
    <Diagram>
      <DiagramGroup title="Workspace Lifecycle" color="purple" className="w-full">
        {/* Step 1: Create */}
        <DiagramNode icon="play" label="1. Create Container" color="indigo" className="w-full" />

        <DiagramSeparator label="Setup Phase (~30s): Secrets available" />

        <DiagramGrid columns={4}>
          <DiagramNode icon="lock" label="Inject Token" color="amber" size="sm" />
          <DiagramNode icon="git" label="Configure git" color="amber" size="sm" />
          <DiagramNode icon="terminal" label="Setup gh CLI" color="amber" size="sm" />
          <DiagramNode icon="unlock" label="Clear tokens" color="pink" size="sm" />
        </DiagramGrid>

        <DiagramSeparator label="Agent Phase: Only ANTHROPIC_API_KEY" />

        <DiagramGrid columns={4}>
          <DiagramNode icon="zap" label="AI Agent" color="purple" size="sm" />
          <DiagramNode icon="git" label="Cached creds" color="emerald" size="sm" />
          <DiagramNode icon="radio" label="Stream events" color="cyan" size="sm" />
          <DiagramNode icon="drive" label="Artifacts" color="pink" size="sm" />
        </DiagramGrid>

        <DiagramSeparator label="Cleanup" />

        <DiagramNode icon="stop" label="2. Destroy Container" color="slate" className="w-full" />
      </DiagramGroup>
    </Diagram>
  );
}

export function ScalingDiagram() {
  return (
    <Diagram>
      {/* Load Balancer */}
      <DiagramGroup title="Load Balancer" color="indigo" columns={1} className="w-full max-w-xs">
        <DiagramNode icon="globe" label="least_conn" color="indigo" />
      </DiagramGroup>

      <DiagramArrow />

      {/* Servers */}
      <DiagramGrid columns={3}>
        <DiagramNode icon="server" label="Syn137 Server 1" color="purple" size="sm" />
        <DiagramNode icon="server" label="Syn137 Server 2" color="purple" size="sm" />
        <DiagramNode icon="server" label="Syn137 Server 3" color="purple" size="sm" />
      </DiagramGrid>

      <DiagramArrow label="Shared state" />

      {/* Data stores */}
      <DiagramGrid columns={3}>
        <DiagramNode icon="database" label="PostgreSQL" color="emerald" size="sm" />
        <DiagramNode icon="zap" label="Redis Cluster" color="amber" size="sm" />
        <DiagramNode icon="drive" label="S3 Storage" color="pink" size="sm" />
      </DiagramGrid>
    </Diagram>
  );
}
