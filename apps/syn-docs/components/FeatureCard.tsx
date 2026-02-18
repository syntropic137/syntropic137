'use client';

import { cn } from '@/lib/cn';
import { Lock, Plug, CheckCircle, Puzzle, Shield, Zap, GitBranch, Layers, Eye, Workflow, Terminal, Globe } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

type IconName = 'lock' | 'plug' | 'check' | 'puzzle' | 'shield' | 'zap' | 'git' | 'layers' | 'eye' | 'workflow' | 'terminal' | 'globe';

interface FeatureCardProps {
  icon: IconName;
  title: string;
  description: string;
  gradient?: 'purple' | 'indigo' | 'pink' | 'cyan' | 'green';
  className?: string;
}

const gradients = {
  purple: 'from-purple-500/10 to-pink-500/10 border-purple-500/20 hover:border-purple-500/40',
  indigo: 'from-indigo-500/10 to-purple-500/10 border-indigo-500/20 hover:border-indigo-500/40',
  pink: 'from-pink-500/10 to-rose-500/10 border-pink-500/20 hover:border-pink-500/40',
  cyan: 'from-cyan-500/10 to-blue-500/10 border-cyan-500/20 hover:border-cyan-500/40',
  green: 'from-emerald-500/10 to-teal-500/10 border-emerald-500/20 hover:border-emerald-500/40',
};

const iconGradients = {
  purple: 'from-purple-400 to-pink-400',
  indigo: 'from-indigo-400 to-purple-400',
  pink: 'from-pink-400 to-rose-400',
  cyan: 'from-cyan-400 to-blue-400',
  green: 'from-emerald-400 to-teal-400',
};

const iconMap: Record<IconName, LucideIcon> = {
  lock: Lock,
  plug: Plug,
  check: CheckCircle,
  puzzle: Puzzle,
  shield: Shield,
  zap: Zap,
  git: GitBranch,
  layers: Layers,
  eye: Eye,
  workflow: Workflow,
  terminal: Terminal,
  globe: Globe,
};

export function FeatureCard({ icon, title, description, gradient = 'indigo', className }: FeatureCardProps) {
  const Icon = iconMap[icon];

  return (
    <div
      className={cn(
        'group relative rounded-xl border bg-gradient-to-br p-5 transition-all duration-300',
        gradients[gradient],
        className
      )}
    >
      <div className="flex items-start gap-4">
        <div className={cn(
          'flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br',
          iconGradients[gradient]
        )}>
          <Icon className="w-6 h-6 text-white" />
        </div>
        <div className="space-y-1">
          <h3 className="font-semibold text-fd-foreground">{title}</h3>
          <p className="text-sm text-fd-muted-foreground">{description}</p>
        </div>
      </div>
    </div>
  );
}

interface FeatureGridProps {
  children: React.ReactNode;
}

export function FeatureGrid({ children }: FeatureGridProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 my-6">
      {children}
    </div>
  );
}
