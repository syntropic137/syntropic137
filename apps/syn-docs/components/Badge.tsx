import { cn } from '@/lib/cn';
import { Bot, Package, Plug, Zap, Shield, Sparkles } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

type BadgeVariant = 'default' | 'purple' | 'indigo' | 'pink' | 'cyan' | 'green' | 'bright';
type IconName = 'bot' | 'package' | 'plug' | 'zap' | 'shield' | 'sparkles';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  icon?: IconName;
  className?: string;
}

const iconMap: Record<IconName, LucideIcon> = {
  bot: Bot,
  package: Package,
  plug: Plug,
  zap: Zap,
  shield: Shield,
  sparkles: Sparkles,
};

/** The old palette names collapse onto Skyline's pill tones. */
const tones: Record<BadgeVariant, 'neutral' | 'accent' | 'success' | 'solid'> = {
  default: 'neutral',
  purple: 'accent',
  indigo: 'accent',
  pink: 'accent',
  cyan: 'accent',
  green: 'success',
  bright: 'solid',
};

export function Badge({ children, variant = 'default', icon, className }: BadgeProps) {
  const Icon = icon ? iconMap[icon] : null;

  return (
    <span className={cn('syn-badge', className)} data-tone={tones[variant]}>
      {Icon && <Icon aria-hidden="true" />}
      {children}
    </span>
  );
}
