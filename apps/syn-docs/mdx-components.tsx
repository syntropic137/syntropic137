import type { MDXComponents } from 'mdx/types';
import defaultMdxComponents from 'fumadocs-ui/mdx';
import { Files, File, Folder } from 'fumadocs-ui/components/files';
import { APIPage } from '@/lib/source';
import { Badge } from '@/components/Badge';
import { Callout } from '@/components/Callout';
import { FeatureCard, FeatureGrid } from '@/components/FeatureCard';
import { GradientButton, ButtonGroup } from '@/components/GradientButton';
import {
  Diagram, DiagramNode, DiagramGroup, DiagramArrow,
  DiagramRow, DiagramColumn, DiagramFlow, DiagramGrid, DiagramSeparator,
  SystemArchitectureDiagram,
  EventSourcingFlowDiagram, TwoEventTypesDiagram, CQRSDiagram,
  DomainModelDiagram, StateMachineDiagram,
  DeploymentArchitectureDiagram, WorkspaceIsolationDiagram, ScalingDiagram,
  // Interactive React Flow diagrams
  SystemArchitectureFlow, EventSourcingFlow, TwoEventTypesFlow,
  CQRSFlow, DomainModelFlow, StateMachineFlow,
  DeploymentArchitectureFlow, WorkspaceIsolationFlow, ScalingFlow,
  PluginEcosystemFlow,
} from '@/components/diagrams';

export function getMDXComponents(components: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
    Callout,
    APIPage,
    Badge,
    FeatureCard,
    FeatureGrid,
    GradientButton,
    ButtonGroup,
    // Diagram primitives
    Diagram,
    DiagramNode,
    DiagramGroup,
    DiagramArrow,
    DiagramRow,
    DiagramColumn,
    DiagramFlow,
    DiagramGrid,
    DiagramSeparator,
    // Pre-built diagrams
    SystemArchitectureDiagram,
    EventSourcingFlowDiagram,
    TwoEventTypesDiagram,
    CQRSDiagram,
    DomainModelDiagram,
    StateMachineDiagram,
    DeploymentArchitectureDiagram,
    WorkspaceIsolationDiagram,
    ScalingDiagram,
    // Interactive React Flow diagrams
    SystemArchitectureFlow,
    EventSourcingFlow,
    TwoEventTypesFlow,
    CQRSFlow,
    DomainModelFlow,
    StateMachineFlow,
    DeploymentArchitectureFlow,
    WorkspaceIsolationFlow,
    ScalingFlow,
    PluginEcosystemFlow,
    // File tree components
    Files,
    File,
    Folder,
    ...components,
  };
}

export function useMDXComponents(components: MDXComponents): MDXComponents {
  return getMDXComponents(components);
}
