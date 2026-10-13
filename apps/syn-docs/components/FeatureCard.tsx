import { cn } from '@/lib/cn';
import { Lock, Plug, CheckCircle, Puzzle, Shield, Zap, GitBranch, Layers, Eye, Workflow, Terminal, Globe } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

type IconName = 'lock' | 'plug' | 'check' | 'puzzle' | 'shield' | 'zap' | 'git' | 'layers' | 'eye' | 'workflow' | 'terminal' | 'globe';

interface FeatureCardProps {
  icon: IconName;
  title: string;
  description: string;
  /**
   * Kept so existing MDX keeps compiling. Every card now uses the one Skyline
   * panel (accent icon tile, panel gradient), as on the landing page, so the
   * old per-card gradients no longer change the look.
   */
  gradient?: 'purple' | 'indigo' | 'pink' | 'cyan' | 'green';
  className?: string;
}

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

export function FeatureCard({ icon, title, description, className }: FeatureCardProps) {
  const Icon = iconMap[icon];

  return (
    <div className={cn('syn-feature-card', className)}>
      <div className="syn-feature-card__icon" aria-hidden="true">
        <Icon />
      </div>
      <div className="syn-feature-card__body">
        <h3 className="syn-feature-card__title">{title}</h3>
        <p className="syn-feature-card__text">{description}</p>
      </div>
    </div>
  );
}

interface FeatureGridProps {
  children: React.ReactNode;
}

export function FeatureGrid({ children }: FeatureGridProps) {
  return <div className="syn-feature-grid not-prose">{children}</div>;
}
