'use client';

import { cn } from '@/lib/cn';
import type { LucideIcon } from 'lucide-react';
import {
  Terminal, Layout, Github, Server, Database, HardDrive,
  Workflow, Eye, Activity, Shield, Zap, GitBranch, Plug,
  Box, Layers, Radio, Send, Lock, Unlock, Play, Pause,
  Square, CheckCircle, XCircle, ArrowDown, ArrowRight,
  Globe, Container, Cpu, MonitorSmartphone,
} from 'lucide-react';

const iconMap: Record<string, LucideIcon> = {
  terminal: Terminal, layout: Layout, github: Github,
  server: Server, database: Database, drive: HardDrive,
  workflow: Workflow, eye: Eye, activity: Activity,
  shield: Shield, zap: Zap, git: GitBranch, plug: Plug,
  box: Box, layers: Layers, radio: Radio, send: Send,
  lock: Lock, unlock: Unlock, play: Play, pause: Pause,
  stop: Square, check: CheckCircle, x: XCircle,
  globe: Globe, container: Container, cpu: Cpu,
  monitor: MonitorSmartphone,
};

type ColorVariant = 'indigo' | 'purple' | 'pink' | 'cyan' | 'slate' | 'emerald' | 'amber';

// SR-71 palette: cold instrument blues, titanium grays, precision feel
const colorStyles: Record<ColorVariant, {
  bg: string;
  border: string;
  icon: string;
  text: string;
  glow: string;
}> = {
  indigo: {
    bg: 'bg-sky-500/8 dark:bg-sky-500/12',
    border: 'border-sky-500/25 dark:border-sky-400/25',
    icon: 'text-sky-500 dark:text-sky-400',
    text: 'text-sky-700 dark:text-sky-300',
    glow: 'shadow-sky-500/15',
  },
  purple: {
    bg: 'bg-blue-500/8 dark:bg-blue-500/12',
    border: 'border-blue-500/25 dark:border-blue-400/25',
    icon: 'text-blue-500 dark:text-blue-400',
    text: 'text-blue-700 dark:text-blue-300',
    glow: 'shadow-blue-500/15',
  },
  pink: {
    bg: 'bg-rose-500/8 dark:bg-rose-500/10',
    border: 'border-rose-500/20 dark:border-rose-400/20',
    icon: 'text-rose-500 dark:text-rose-400',
    text: 'text-rose-700 dark:text-rose-300',
    glow: 'shadow-rose-500/15',
  },
  cyan: {
    bg: 'bg-cyan-500/8 dark:bg-cyan-500/12',
    border: 'border-cyan-500/25 dark:border-cyan-400/25',
    icon: 'text-cyan-500 dark:text-cyan-400',
    text: 'text-cyan-700 dark:text-cyan-300',
    glow: 'shadow-cyan-500/15',
  },
  slate: {
    bg: 'bg-zinc-500/8 dark:bg-zinc-500/12',
    border: 'border-zinc-500/25 dark:border-zinc-400/25',
    icon: 'text-zinc-500 dark:text-zinc-400',
    text: 'text-zinc-600 dark:text-zinc-300',
    glow: 'shadow-zinc-500/15',
  },
  emerald: {
    bg: 'bg-teal-500/8 dark:bg-teal-500/12',
    border: 'border-teal-500/25 dark:border-teal-400/25',
    icon: 'text-teal-500 dark:text-teal-400',
    text: 'text-teal-700 dark:text-teal-300',
    glow: 'shadow-teal-500/15',
  },
  amber: {
    bg: 'bg-amber-500/8 dark:bg-amber-500/10',
    border: 'border-amber-500/20 dark:border-amber-400/20',
    icon: 'text-amber-500 dark:text-amber-400',
    text: 'text-amber-700 dark:text-amber-300',
    glow: 'shadow-amber-500/15',
  },
};

// --- Node ---

interface DiagramNodeProps {
  icon: string;
  label: string;
  sublabel?: string;
  color?: ColorVariant;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function DiagramNode({ icon, label, sublabel, color = 'indigo', size = 'md', className }: DiagramNodeProps) {
  const Icon = iconMap[icon] ?? Box;
  const style = colorStyles[color];
  const sizes = {
    sm: 'px-3 py-2 text-xs gap-2',
    md: 'px-4 py-2.5 text-sm gap-2.5',
    lg: 'px-5 py-3.5 text-base gap-3',
  };
  const iconSizes = { sm: 'w-3.5 h-3.5', md: 'w-4 h-4', lg: 'w-5 h-5' };

  return (
    <div className={cn(
      'flex items-center justify-center rounded-lg border backdrop-blur-sm transition-all min-w-0',
      sizes[size], style.bg, style.border, className,
    )}>
      <Icon className={cn(iconSizes[size], style.icon, 'shrink-0')} />
      <div className="flex flex-col min-w-0">
        <span className={cn('font-medium whitespace-nowrap', style.text)}>{label}</span>
        {sublabel && (
          <span className="text-[10px] text-fd-muted-foreground leading-tight whitespace-nowrap">{sublabel}</span>
        )}
      </div>
    </div>
  );
}

// --- Group ---

interface DiagramGroupProps {
  title: string;
  color?: ColorVariant;
  children: React.ReactNode;
  columns?: 1 | 2 | 3 | 4;
  className?: string;
}

const gridCols: Record<number, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-2',
  3: 'grid-cols-3',
  4: 'grid-cols-4',
};

export function DiagramGroup({ title, color = 'slate', children, columns, className }: DiagramGroupProps) {
  const style = colorStyles[color];

  return (
    <div className={cn(
      'rounded-xl border p-4 backdrop-blur-sm',
      style.bg, style.border, className,
    )}>
      <div className={cn('text-xs font-semibold uppercase tracking-wider mb-3', style.text)}>
        {title}
      </div>
      {columns ? (
        <div className={cn('grid gap-2', gridCols[columns])}>
          {children}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {children}
        </div>
      )}
    </div>
  );
}

// --- Arrow ---

interface DiagramArrowProps {
  direction?: 'down' | 'right';
  label?: string;
  className?: string;
}

export function DiagramArrow({ direction = 'down', label, className }: DiagramArrowProps) {
  const ArrowIcon = direction === 'down' ? ArrowDown : ArrowRight;

  return (
    <div className={cn(
      'flex items-center justify-center gap-1.5',
      direction === 'down' ? 'flex-col py-0.5' : 'flex-row px-1',
      className,
    )}>
      {label && (
        <span className="text-[10px] text-fd-muted-foreground font-medium">{label}</span>
      )}
      <ArrowIcon className="w-4 h-4 text-fd-muted-foreground/60" />
    </div>
  );
}

// --- Grid: evenly distributed cells ---

interface DiagramGridProps {
  children: React.ReactNode;
  columns?: 2 | 3 | 4;
  className?: string;
}

export function DiagramGrid({ children, columns = 3, className }: DiagramGridProps) {
  return (
    <div className={cn('grid gap-3 w-full', gridCols[columns], className)}>
      {children}
    </div>
  );
}

// --- Row / Column layout ---

interface DiagramLayoutProps {
  children: React.ReactNode;
  className?: string;
}

export function DiagramRow({ children, className }: DiagramLayoutProps) {
  return (
    <div className={cn('flex items-center justify-center gap-3', className)}>
      {children}
    </div>
  );
}

export function DiagramColumn({ children, className }: DiagramLayoutProps) {
  return (
    <div className={cn('flex flex-col items-center gap-2', className)}>
      {children}
    </div>
  );
}

// --- Container ---

export function Diagram({ children, className }: DiagramLayoutProps) {
  return (
    <div className={cn(
      'my-6 rounded-xl border border-fd-border bg-fd-card/50 p-6 overflow-x-auto',
      className,
    )}>
      <div className="flex flex-col items-center gap-3 min-w-fit">
        {children}
      </div>
    </div>
  );
}

// --- Flow (horizontal pipeline with arrows between items) ---

interface DiagramFlowProps {
  children: React.ReactNode;
  label?: string;
  className?: string;
}

export function DiagramFlow({ children, label, className }: DiagramFlowProps) {
  const items = Array.isArray(children) ? children : [children];
  return (
    <div className={cn('flex flex-col items-center gap-1', className)}>
      {label && (
        <span className="text-[10px] text-fd-muted-foreground font-medium mb-1">{label}</span>
      )}
      <div className="flex items-center justify-center gap-1.5">
        {items.map((child, i) => (
          <div key={i} className="flex items-center gap-1.5">
            {i > 0 && <ArrowRight className="w-3.5 h-3.5 text-fd-muted-foreground/50 shrink-0" />}
            {child}
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Separator ---

export function DiagramSeparator({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 w-full px-2 py-1">
      <div className="flex-1 h-px bg-gradient-to-r from-transparent via-fd-border to-transparent" />
      {label && (
        <span className="text-[10px] text-fd-muted-foreground font-medium shrink-0">{label}</span>
      )}
      <div className="flex-1 h-px bg-gradient-to-r from-transparent via-fd-border to-transparent" />
    </div>
  );
}
