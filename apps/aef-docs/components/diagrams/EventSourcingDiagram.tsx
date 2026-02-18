'use client';

import {
  Diagram, DiagramGroup, DiagramNode, DiagramArrow,
  DiagramRow, DiagramGrid, DiagramFlow, DiagramSeparator,
} from './DiagramPrimitives';

export function EventSourcingFlowDiagram() {
  return (
    <Diagram>
      <DiagramFlow label="Event Sourcing Pipeline">
        <DiagramNode icon="send" label="Command" color="indigo" />
        <DiagramNode icon="shield" label="Aggregate" sublabel="Validate" color="purple" />
        <DiagramNode icon="zap" label="Domain Event" color="pink" />
        <DiagramNode icon="database" label="Event Store" color="cyan" />
        <DiagramNode icon="layers" label="Projections" color="emerald" />
        <DiagramNode icon="eye" label="Read Models" color="amber" />
      </DiagramFlow>
    </Diagram>
  );
}

export function TwoEventTypesDiagram() {
  return (
    <Diagram>
      <DiagramGrid columns={2} className="items-start">
        {/* Domain Events */}
        <DiagramGroup title="Domain Events" color="purple" className="h-full">
          <DiagramFlow>
            <DiagramNode icon="send" label="Command" color="indigo" size="sm" />
            <DiagramNode icon="shield" label="Aggregate" color="purple" size="sm" />
            <DiagramNode icon="zap" label="Event" color="pink" size="sm" />
          </DiagramFlow>
          <DiagramArrow label="gRPC" />
          <DiagramRow>
            <DiagramNode icon="database" label="Event Store" color="purple" size="sm" />
          </DiagramRow>
        </DiagramGroup>

        {/* Observability Events */}
        <DiagramGroup title="Observability Events" color="cyan" className="h-full">
          <DiagramFlow>
            <DiagramNode icon="zap" label="Agent" color="cyan" size="sm" />
            <DiagramNode icon="eye" label="Observation" color="cyan" size="sm" />
            <DiagramNode icon="check" label="Schema Check" color="emerald" size="sm" />
          </DiagramFlow>
          <DiagramArrow label="Direct insert" />
          <DiagramRow>
            <DiagramNode icon="database" label="TimescaleDB" sublabel="Hypertable" color="cyan" size="sm" />
          </DiagramRow>
        </DiagramGroup>
      </DiagramGrid>
    </Diagram>
  );
}

export function CQRSDiagram() {
  return (
    <Diagram>
      <DiagramGrid columns={2} className="items-start">
        <DiagramGroup title="Write Side" color="purple" className="h-full">
          <DiagramFlow>
            <DiagramNode icon="send" label="Commands" color="indigo" size="sm" />
            <DiagramNode icon="shield" label="Aggregates" color="purple" size="sm" />
            <DiagramNode icon="zap" label="Events" color="pink" size="sm" />
          </DiagramFlow>
          <DiagramArrow />
          <DiagramRow>
            <DiagramNode icon="database" label="Event Store" color="purple" size="sm" />
          </DiagramRow>
        </DiagramGroup>

        <DiagramGroup title="Read Side" color="cyan" className="h-full">
          <DiagramFlow>
            <DiagramNode icon="layers" label="Projections" color="cyan" size="sm" />
            <DiagramNode icon="zap" label="Redis Cache" color="amber" size="sm" />
          </DiagramFlow>
          <DiagramArrow />
          <DiagramRow>
            <DiagramNode icon="server" label="Query API" sublabel="sub-ms cached" color="emerald" size="sm" />
          </DiagramRow>
        </DiagramGroup>
      </DiagramGrid>
    </Diagram>
  );
}

export function DomainModelDiagram() {
  return (
    <Diagram>
      {/* Four bounded contexts in an even grid */}
      <DiagramGrid columns={4} className="items-start">
        <DiagramGroup title="Orchestration" color="indigo">
          <DiagramNode icon="workflow" label="Workflow" color="indigo" size="sm" />
          <DiagramNode icon="play" label="Execution" color="indigo" size="sm" />
          <DiagramNode icon="container" label="Workspace" color="indigo" size="sm" />
        </DiagramGroup>

        <DiagramGroup title="Sessions" color="purple">
          <DiagramNode icon="activity" label="Session" color="purple" size="sm" />
        </DiagramGroup>

        <DiagramGroup title="GitHub" color="pink">
          <DiagramNode icon="github" label="Installation" color="pink" size="sm" />
          <DiagramNode icon="zap" label="Triggers" color="pink" size="sm" />
        </DiagramGroup>

        <DiagramGroup title="Artifacts" color="cyan">
          <DiagramNode icon="drive" label="Artifact Store" color="cyan" size="sm" />
        </DiagramGroup>
      </DiagramGrid>

      <DiagramSeparator label="Event-driven communication" />

      <DiagramFlow>
        <DiagramNode icon="git" label="Trigger" color="pink" size="sm" />
        <DiagramNode icon="workflow" label="Workflow" color="indigo" size="sm" />
        <DiagramNode icon="play" label="Execution" color="indigo" size="sm" />
        <DiagramNode icon="container" label="Workspace" color="indigo" size="sm" />
        <DiagramNode icon="activity" label="Session" color="purple" size="sm" />
        <DiagramNode icon="drive" label="Artifact" color="cyan" size="sm" />
      </DiagramFlow>
    </Diagram>
  );
}

export function StateMachineDiagram() {
  return (
    <Diagram>
      {/* Initial flow */}
      <DiagramFlow>
        <DiagramNode icon="pause" label="PENDING" color="slate" />
        <DiagramNode icon="play" label="RUNNING" color="indigo" />
      </DiagramFlow>

      <DiagramArrow label="transitions" />

      {/* Terminal states in even grid */}
      <DiagramGrid columns={4}>
        <div className="flex flex-col items-center gap-1.5">
          <DiagramNode icon="pause" label="PAUSED" color="amber" className="w-full" />
          <span className="text-[10px] text-fd-muted-foreground">pause / resume</span>
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <DiagramNode icon="check" label="COMPLETED" color="emerald" className="w-full" />
          <span className="text-[10px] text-fd-muted-foreground">success</span>
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <DiagramNode icon="x" label="FAILED" color="pink" className="w-full" />
          <span className="text-[10px] text-fd-muted-foreground">error</span>
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <DiagramNode icon="stop" label="CANCELLED" color="slate" className="w-full" />
          <span className="text-[10px] text-fd-muted-foreground">cancel</span>
        </div>
      </DiagramGrid>
    </Diagram>
  );
}
