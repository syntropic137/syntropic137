'use client';

import Link from 'next/link';
import { cn } from '@/lib/cn';
import { ArrowRight, Rocket, Terminal, BookOpen, Zap } from 'lucide-react';

type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'bright';

interface GradientButtonProps {
  href: string;
  children: React.ReactNode;
  variant?: ButtonVariant;
  icon?: 'rocket' | 'terminal' | 'book' | 'zap';
  className?: string;
}

const variants = {
  primary: 'bg-gradient-to-r from-indigo-500 to-purple-500 hover:from-indigo-600 hover:to-purple-600 text-white shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40',
  secondary: 'bg-gradient-to-r from-slate-700 to-slate-800 hover:from-slate-600 hover:to-slate-700 text-white dark:from-slate-600 dark:to-slate-700 dark:hover:from-slate-500 dark:hover:to-slate-600',
  outline: 'border-2 border-fd-foreground/20 hover:border-fd-foreground/40 text-fd-foreground hover:bg-fd-foreground/5',
  bright: 'bg-gradient-to-r from-violet-500 to-purple-500 hover:from-violet-600 hover:to-purple-600 text-white font-semibold shadow-lg shadow-purple-500/30 hover:shadow-purple-500/50',
};

const icons = {
  rocket: Rocket,
  terminal: Terminal,
  book: BookOpen,
  zap: Zap,
};

export function GradientButton({ href, children, variant = 'primary', icon, className }: GradientButtonProps) {
  const Icon = icon ? icons[icon] : null;

  return (
    <Link
      href={href}
      className={cn(
        'inline-flex items-center gap-2 px-5 py-2.5 rounded-full font-medium text-sm transition-all duration-200',
        variants[variant],
        className
      )}
    >
      {Icon && <Icon className="w-4 h-4" />}
      {children}
      <ArrowRight className="w-4 h-4" />
    </Link>
  );
}

interface ButtonGroupProps {
  children: React.ReactNode;
  className?: string;
}

export function ButtonGroup({ children, className }: ButtonGroupProps) {
  return (
    <div className={cn('flex flex-wrap gap-3 my-6', className)}>
      {children}
    </div>
  );
}
