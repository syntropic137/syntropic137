'use client';

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

const variants: Record<BadgeVariant, string> = {
  default: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  purple: 'bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300 border border-purple-200 dark:border-purple-500/30',
  indigo: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-500/30',
  pink: 'bg-pink-100 text-pink-700 dark:bg-pink-500/20 dark:text-pink-300 border border-pink-200 dark:border-pink-500/30',
  cyan: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-500/20 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-500/30',
  green: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30',
  bright: 'bg-[#E6FF00] text-black font-semibold',
};

export function Badge({ children, variant = 'default', icon, className }: BadgeProps) {
  const Icon = icon ? iconMap[icon] : null;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium',
        variants[variant],
        className
      )}
    >
      {Icon && <Icon className="w-3.5 h-3.5" />}
      {children}
    </span>
  );
}
