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

/** Skyline buttons: solid accent (primary, bright), raised control (secondary), hairline (outline). */
const styles: Record<ButtonVariant, 'solid' | 'control' | 'outline'> = {
  primary: 'solid',
  bright: 'solid',
  secondary: 'control',
  outline: 'outline',
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
    <Link href={href} className={cn('syn-button not-prose', className)} data-variant={styles[variant]}>
      {Icon && <Icon aria-hidden="true" />}
      {children}
      <ArrowRight aria-hidden="true" />
    </Link>
  );
}

interface ButtonGroupProps {
  children: React.ReactNode;
  className?: string;
}

export function ButtonGroup({ children, className }: ButtonGroupProps) {
  return <div className={cn('syn-button-group not-prose', className)}>{children}</div>;
}
