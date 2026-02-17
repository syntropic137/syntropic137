import type { MDXComponents } from 'mdx/types';
import defaultMdxComponents from 'fumadocs-ui/mdx';
import { APIPage } from '@/lib/source';
import { Badge } from '@/components/Badge';
import { FeatureCard, FeatureGrid } from '@/components/FeatureCard';
import { GradientButton, ButtonGroup } from '@/components/GradientButton';
import {
  Diagram, DiagramNode, DiagramGroup, DiagramArrow,
  DiagramRow, DiagramColumn, DiagramFlow, DiagramGrid, DiagramSeparator,
  SystemArchitectureDiagram,
  EventSourcingFlowDiagram, TwoEventTypesDiagram, CQRSDiagram,
  DomainModelDiagram, StateMachineDiagram,
  DeploymentArchitectureDiagram, WorkspaceIsolationDiagram, ScalingDiagram,
} from '@/components/diagrams';

export function getMDXComponents(components: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
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
    ...components,
  };
}

export function useMDXComponents(components: MDXComponents): MDXComponents {
  return getMDXComponents(components);
}
