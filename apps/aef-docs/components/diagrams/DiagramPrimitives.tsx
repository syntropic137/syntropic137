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

const colorStyles: Record<ColorVariant, {
  bg: string;
  border: string;
  icon: string;
  text: string;
  glow: string;
}> = {
  indigo: {
    bg: 'bg-indigo-500/10 dark:bg-indigo-500/15',
    border: 'border-indigo-500/30 dark:border-indigo-400/30',
    icon: 'text-indigo-500 dark:text-indigo-400',
    text: 'text-indigo-700 dark:text-indigo-300',
    glow: 'shadow-indigo-500/20',
  },
  purple: {
    bg: 'bg-purple-500/10 dark:bg-purple-500/15',
    border: 'border-purple-500/30 dark:border-purple-400/30',
    icon: 'text-purple-500 dark:text-purple-400',
    text: 'text-purple-700 dark:text-purple-300',
    glow: 'shadow-purple-500/20',
  },
  pink: {
    bg: 'bg-pink-500/10 dark:bg-pink-500/15',
    border: 'border-pink-500/30 dark:border-pink-400/30',
    icon: 'text-pink-500 dark:text-pink-400',
    text: 'text-pink-700 dark:text-pink-300',
    glow: 'shadow-pink-500/20',
  },
  cyan: {
    bg: 'bg-cyan-500/10 dark:bg-cyan-500/15',
    border: 'border-cyan-500/30 dark:border-cyan-400/30',
    icon: 'text-cyan-500 dark:text-cyan-400',
    text: 'text-cyan-700 dark:text-cyan-300',
    glow: 'shadow-cyan-500/20',
  },
  slate: {
    bg: 'bg-slate-500/10 dark:bg-slate-500/15',
    border: 'border-slate-500/30 dark:border-slate-400/30',
    icon: 'text-slate-500 dark:text-slate-400',
    text: 'text-slate-700 dark:text-slate-300',
    glow: 'shadow-slate-500/20',
  },
  emerald: {
    bg: 'bg-emerald-500/10 dark:bg-emerald-500/15',
    border: 'border-emerald-500/30 dark:border-emerald-400/30',
    icon: 'text-emerald-500 dark:text-emerald-400',
    text: 'text-emerald-700 dark:text-emerald-300',
    glow: 'shadow-emerald-500/20',
  },
  amber: {
    bg: 'bg-amber-500/10 dark:bg-amber-500/15',
    border: 'border-amber-500/30 dark:border-amber-400/30',
    icon: 'text-amber-500 dark:text-amber-400',
    text: 'text-amber-700 dark:text-amber-300',
    glow: 'shadow-amber-500/20',
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
